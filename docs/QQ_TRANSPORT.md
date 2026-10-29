# QQ transport owner: native-platform.ts and the QQ World integration

The port requires an internal tool named `qq_companion_transport` available to role `astrbot-native-transport`. It must reject ordinary model/tool callers. It must check current pause state and conversation scope before invoking platform APIs. Read actions used by the unmodified SDK include login/status/friend/group metadata, message/forward/history reads, credentials/cookies/CSRF and input status.

`cortico_qzone_authorize` must check that Qzone is enabled and that pause, quiet hours and stream suppression permit a write. `cortico_tts` must use the existing voice pipeline, not an unrelated voice service. Retraction must only recall known own messages in the current allowed scope. `native-platform.ts` performs the port-side validation and uses existing `qq_send`, `qq_send_audio`, `qq_recall`, `qq_qzone_post` tools for writes. A Qzone result must contain a platform post ID; an unknown result is not retried as confirmed success.

This contract was accepted with a customized QQ World in the source deployment. The reference implementation here is integration material, not a drop-in replacement QQ plugin; its caller must supply the current scope, pause and policy checks. The four public packages do not bundle or install a QQ client, voice model, SnowLuma, NapCat or credentials. Standard OneBot support alone does not satisfy this contract.

The reference file is derived from Kpect10086's local QQ ProMAX integration, whose package LICENSE is AGPL-3.0-or-later; that original license is retained as LICENSE-QQ-REFERENCE. This does not relicense the three menglimi plugins.
