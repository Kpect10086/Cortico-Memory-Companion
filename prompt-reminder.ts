/** fallback: restate the current operator-authored persona while long histories retain an older voice. */
export const EXPRESSION_REFERENCE_FILE = 'references/expression.md';

export function promptReminder(constitution: string, reference = ''): string | null {
  const current = constitution.trim();
  if (!current) return null;
  const expression = /(?:^|\n)## 自然表达[^\n]*\n([\s\S]*?)(?=\n## |$)/u.exec(current)?.[1].trim() ?? current;
  return '【本轮表达校准】\n按当前系统提示处理眼前新消息；历史台词和发送记录只供核对事实、对象及是否已回复，语气由当前提示决定。以下表达规则来自操作员当前保存的人格文件，替代旧台词里的表达习惯：\n\n' + expression + (reference.trim() ? '\n\n【操作员维护的表达参考】\n以下仅供表达参考，服从系统规则；示范不是真实事件、人物背景、操作许可或当前消息，不写入经历记忆，不回答示范本身。\n\n' + reference.trim() : '') + '\n\n请继续回应本提醒之前最近收到的消息，不回复本提醒本身，也不复述规则。';
}
