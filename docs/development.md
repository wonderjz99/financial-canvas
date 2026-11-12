# Financial Canvas 开发与验证

Python 3.10+，推荐 `.python-version` 的 3.12。核心不需要 pip 依赖；Node.js 22+ 和锁定的 Playwright 仅用于开发验收。Windows PowerShell 可设置 `$env:PYTHONUTF8 = "1"`，并把 python3 换成实际命令名。

```bash
python3 -B scripts/verify.py
```

公开版根目录的 PUBLIC_RELEASE.json 使验证默认采用单公司模式；也可以显式 `--scope v2`。验证运行合成契约与公开内容边界测试、JavaScript 语法检查，并核对随附示例的 SHA256 和来源，不读取研发仓库数据或访问金融服务。

```bash
npm ci --ignore-scripts
npx playwright install chromium
npm run check:js
python3 -B scripts/verify.py --browser
```

Linux 缺系统库时使用 `npx playwright install --with-deps chromium`。安装阶段需要网络；随后生成合成测试页面与浏览器交互完全离线。浏览器仅准备 `.local/browser/v2.html`，不运行 V1 构建，不读取个人浏览器状态。三视口为 1280×950、390×844、320×844。

如果 Python 命令名不是 python3，设置 FV_PYTHON，例如 Windows PowerShell 的 `$env:FV_PYTHON = "python"`。单独运行浏览器可用 `npm run test:browser`，限定视口可加 `-- --project=desktop`。

测试检查单公司、期间、模式、播放、来源、六类分析、控制台及网络请求。截图和 trace 留在被忽略的 test-results/ 与 playwright-report/；不把合成金额或浏览器通过当作真实披露核验，也不声称覆盖 Firefox/Safari。

公开路径检查：

```bash
python3 scripts/check_public.py
python3 scripts/check_public.py --tracked --history
```

第二条需要当前目录是独立的 Git 仓库，并检查 Git 索引及已获取历史中是否出现被排除路径。仅允许 examples/reports/ 下的 COST、AAPL、ADBE 三个报告；其 provenance.json 必须匹配文件 SHA256、单公司身份、年度、币种、截止日期和 SEC 来源。历史提交中的示例也执行来源检查，不能用后续替换掩盖旧供应商数据。CI 使用完整历史获取；它是发行内容检查，不是完整密钥或漏洞审计。

README 的 docs/images/ 截图来自实际示例。更新示例时离线构建到新路径、复核报告和出处、同步 provenance.json，再用浏览器检查桌面及 390px/320px 交互并重拍截图。不要直接编辑 HTML 中的金额或图形，也不要复制工作目录、缓存或原始申报。

CI 的待发布提交应通过 Linux Python 3.10/3.12、Windows Python 3.12 和 Chromium。工作流不部署网站、不调用金融服务，权限为仓库只读。package.json 中 private: true 防止误发布开发依赖包，不影响 GitHub 可见性。

本发行版没有 V1 真实快照及生成器，请勿使用 full 验证模式。共享模块中保留的旧函数不作为公开使用入口。数据与新报告放在 .local/、reports/，不提交；自有代码采用 MIT，第三方资料另按其适用条件处理。
