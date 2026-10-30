# 多语言

## 支持的语言

`zh` 简体中文 · `en` English · `ja` 日本語 · `ko` 한국어

切换：

```bash
memoir lang ja        # 写进配置，长期生效
memoir --lang ko stats   # 只影响这一次
MEMOIR_LANG=en memoir today  # 环境变量，优先级最高
```

## 翻译的不只是界面

每个语言包里同时装着 **界面文案** 和 **提示词模板**。切到日文时，模型收到的指令、复盘的五段标题、给你的总结，全是日文。

这意味着：**换语言 = 换一个母语者在跟你说话**，不是给英文界面套层皮。

## 语言包结构

`memoir/locales/zh.json`：

```json
{
  "meta":      { "name": "简体中文", "code": "zh" },
  "cli":       { "add_ok": "已记下 #{id}（{kind}）" },
  "report":    { "title": "{date} · 今日复盘", "sections": { "events": "今天做了什么" } },
  "persona":   { "title": "我眼里的你" },
  "scheduler": { "started": "夜间复盘守护已启动…" },
  "prompts":   { "review_system": "…", "review_schema": "…" }
}
```

`{name}` 是占位符，按传参替换。

## 回退规则

当前语言缺键 → 退到 `en` → 退到 `zh` → 返回键名本身。

所以加语言时可以只翻一半，不会崩，只会露几个英文。

## 加一门新语言

1. 复制 `memoir/locales/en.json` 成 `xx.json`
2. 改 `meta.code` 和 `meta.name`
3. 翻译各段（提示词那段最重要，别机翻了事）
4. 在 `memoir/config.py` 的 `LANG_CHOICES` 和 `memoir/cli.py` 里加进选项
5. 跑测试：`python tests/test_smoke.py`（会检查核心键是否齐全）

## 翻译提示词时注意

- **保留 JSON 结构描述**，模型靠它输出可解析的东西
- **不要直译语气**。中文的"不说教"翻成日文是"説教しない"，韩文是"설교하지 않기"，英文是 "no lecturing"——意思对就行
- **`persona_schema` 里的 key 列表**可以本地化（中文写"性格|价值观"，英文写 "character|values"），模型会跟着用
- 改完最好跑一次真实复盘，看模型有没有按格式输出
