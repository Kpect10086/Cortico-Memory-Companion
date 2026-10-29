import { existsSync, readFileSync } from 'node:fs';
import type { ToolDef } from 'cortico/core/types.ts';
import type { GitWorkspaceMemory } from './base/persona/memory.ts';

/** Review the resulting document so edits cannot assemble unsafe text across fragments. */
export function reviewWorkspaceTools(tools: ToolDef[], memory: GitWorkspaceMemory, review: (text: string) => Promise<string>, protectedFiles: string[] = []): ToolDef[] {
  tools = tools.map(original => {
    const tool = {...original};
    if (['write_file','append_file','edit_file','delete_file','rename_file','move_file','save_blob'].includes(tool.name)) {
      const handler = tool.handler;
      tool.handler = async (args,ctx) => {
        try {
          const paths = ['path','from','to','old_path','new_path'].map(key => args[key]).filter(value => typeof value === 'string');
          const fixed = protectedFiles.map(file => memory.insideWorkspace(file).toLowerCase());
          if (paths.some(path => fixed.some(file => {
            const target = memory.insideWorkspace(String(path)).toLowerCase();
            return target === file || file.startsWith(target + '/') || file.startsWith(target + '\\');
          }))) return '[write blocked] 固定宪法与身份资料只允许控制台操作员修改，自动学习和聊天工具不能改写。';
        } catch {return '[write blocked] 文件路径无效';}
        return handler(args,ctx);
      };
    }
    return tool;
  });
  const write = tools.find(tool => tool.name === 'write_file');
  return tools.map(original => {
    const tool = {...original};
    if (['read_file','grep_files'].includes(tool.name)) return {...tool,handler:async (args,ctx) => {
      const result = await tool.handler(args,ctx);
      if (typeof result !== 'string') return result;
      try {return await review(result);} catch {return '[read failed] 内容审核不可用，未返回正文';}
    }};
    if (!write || !['write_file','append_file','edit_file'].includes(tool.name)) return tool;
    return {...tool, handler: async (args, ctx) => {
      try {
        const path = String(args.path ?? '');
        const abs = memory.insideWorkspace(path);
        const previous = existsSync(abs) ? readFileSync(abs, 'utf8') : null;
        let text = String(args.content ?? '');
        if (tool.name === 'append_file') {
          const prev = previous ?? '';
          text = prev + (prev && !prev.endsWith('\n') ? '\n' : '') + text;
        } else if (tool.name === 'edit_file') {
          if (previous === null) return tool.handler(args, ctx);
          const prev = previous;
          const old = String(args.old_string ?? '');
          const replacement = String(args.new_string ?? '');
          if (!old || old === replacement || !prev.includes(old) || (args.replace_all !== true && prev.split(old).length !== 2)) return tool.handler(args, ctx);
          text = args.replace_all === true ? prev.split(old).join(replacement) : prev.replace(old, () => replacement);
        }
        const safe = await review(text);
        if ((existsSync(abs) ? readFileSync(abs, 'utf8') : null) !== previous) return '[write failed] 文件在审核期间已变化，请重新读取后重试';
        return safe === text ? tool.handler(args, ctx) : write.handler({...args, path, content: safe}, ctx);
      } catch { return '[write failed] 内容审核或文件读取不可用，未保存正文'; }
    }};
  });
}
