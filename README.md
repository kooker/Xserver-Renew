


# **Xserver 游戏服 (xmgame) 多账号自动续期系统**。
## 前期准备：关闭邮件验证功能

> ⚠️ **重要**：否则脚本会因邮件验证而失败。不審なログイン時の認証` を「無効」に設定変更してください
https://secure.xserver.ne.jp/xapanel/myaccount/account/loginsecurity/input

<img src="https://github.com/user-attachments/assets/ede29051-41e0-44fc-911d-95501e70a5fd" width="800">

### GitHub 环境变量 (Secrets) 配置操作

1. 进入你的 GitHub 仓库主页。
2. 依次点击顶部菜单栏的 **Settings** -> 左侧边栏的 **Secrets and variables** -> **Actions**。
3. 点击 **New repository secret**，依次添加以下 3 个环境变量：

#### 🔴 第1个：`XSERVER_ACCOUNTS` (账号列表)
严格使用 JSON 格式，注意最后一个账号}没有逗号。
```json
[
  {
    "username": "你的第一个账号@gmail.com",
    "password": "你的第一个密码"
  },
  {
    "username": "你的第二个账号@qq.com",
    "password": "你的第二个密码"
  }
]
```

#### 🔴 第2个：`TELEGRAM_BOT_TOKEN`
填入你通过 BotFather 申请的机器人 Token，例如：
`123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`

#### 🔴 第3个：`TELEGRAM_CHAT_ID`
填入接收通知的用户或群组 ID，例如：
`123456789` 或 `-100123456789`

---

### Python 版的独特优势：
1. **代码同步/顺序性更强**：Node.js 中随处可见的 `await`、`async` 以及潜在的 Promise 地狱在 Python `sync_playwright` 中被完全抹平，代码执行逻辑像瀑布一样自上而下，出 BUG 的概率更低。
2. **正则捕捉极其精准**：借助 `re` 模块提取下一次可续期的时间（例如 "*更新をご希望の場合は、2024/04/01 以降にお試しください*."），Python 表现得比原版 Node.js 更原生和稳定。
3. **完美的资源释放**：用 `finally:` 配合 `context.close()` 杜绝了内存泄露问题，这在工业级脚本多账号循环挂机场景下极其重要。
