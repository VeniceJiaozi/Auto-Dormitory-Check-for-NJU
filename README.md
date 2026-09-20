# 威尼斯饺子 QQ点名机器人

QQ群成员 @机器人 发送「查未点名」/「点名」，机器人自动查询点名系统，并将未晚点名人员名单回复到群里。

- 项目需求与进度：见 [PROJECT_MASTER.md](PROJECT_MASTER.md)（单一事实来源）
- AI 协作规范：见 [Project_init_prompt.md](Project_init_prompt.md)
- QQ 官方 Bot API 备忘：见 [docs/qq_bot_api.md](docs/qq_bot_api.md)
- **其他班级想照着一套搭：见 [docs/班级机器人搭建教程.pdf](docs/班级机器人搭建教程.pdf)**（零编程基础可跟做，源码版为同名 .html）
- 技术栈：Python（纯标准库）+ QQ 开放平台官方 Bot API + 腾讯云 SCF 云函数
