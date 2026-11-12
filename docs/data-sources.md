# 资料来源和版本

V2 使用 SEC ticker 目录识别发行人，用 submissions 核对身份和年度申报，并从 Company Facts 整理标准实体级事实。根据缺口读取申报 HTML/inline XBRL 或经核对的公司官方 IR；自定义标签、分部和完整调节表不能只靠 Company Facts 保证覆盖。

SEC 的数据接口说明见 [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)，访问标识与节流要求见 [Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)。程序按 URL 和内容 SHA256 保存版本与获取时间，不把失败响应覆盖到成功版本。

首次联网前可通过 SEC_USER_AGENT 或 prepare 的 --user-agent 提供项目名与联系标识。默认复用有效缓存；--refresh 获取新版本，失败且有有效缓存时注明旧版本，--offline 只使用已有有效缓存。build 不联网。

资料默认只留本机 .local/v2/。公开发行版不附真实原件、供应商响应或原开发机器缓存，合成测试的发行人、金额和出处只是程序输入形状，不能引用为实际披露。

取得或能读取材料不自动决定其再分发条件；项目 MIT 许可不替第三方材料授予许可。范围见 [第三方说明](../THIRD_PARTY_NOTICES.md)。
