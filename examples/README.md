# 财务画布报告示例

这里是使用 Financial Canvas 和官方披露生成的真实单公司报告。**下载 HTML 后用浏览器打开，或克隆仓库后直接打开对应文件；GitHub 文件页本身显示的是 HTML 源码。**

| 示例 | 已披露完整财年 | 币种 | 截止日期 |
| --- | --- | --- | --- |
| [Costco / COST](reports/COST.html) | FY2022–FY2026 | USD | 2026-11-12 |
| [Apple / AAPL](reports/AAPL.html) | FY2022–FY2026 | USD | 2026-11-12 |
| [Adobe / ADBE](reports/ADBE.html) | FY2021–FY2025 | USD | 2026-11-12 |

每份 HTML 仅内嵌一家公司的事实和交互，离线打开不会请求网络。源事实为 SEC、对官方 SEC 申报的原文观察及固定计算，不含 Futu 来源的事实；原始申报、工作目录和缓存没有随示例打包。精确版本、来源和 SHA256 见 [provenance.json](provenance.json)，逐项出处也可在报告内下钻。

这些是有明确缺口的报告，不是完整财务审计。COST 最新年度完整 CFO 行集已经审阅；其他完整调节、受限现金细节和主营跨年可比性按各份报告的实际说明保留缺口。示例固定于上述日期，不会随打开自动刷新。

另可直接访问维护者提供的 [PDD 在线历史示例](https://value.wonderjz.workers.dev/reports/financial-visualizer?symbol=PDD)。这是既有 WonderValue 多公司页面，包含不同的历史数据补充路径；链接用于展示，未将该旧页面或其数据复制进本仓库。

Financial Canvas 的代码和界面采用 [MIT](../LICENSE)；第三方原始披露不因该许可获得额外授权，范围见 [第三方说明](../THIRD_PARTY_NOTICES.md)。
