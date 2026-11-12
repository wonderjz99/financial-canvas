# Skill 使用

本仓库的 `skills/financial-statement-visuals/` 包含 AI 研究说明和会计参考。它不是模型服务或独立安装程序。

在可读取文件、运行 Python、阅读官方披露的 AI 环境中打开仓库，直接请求：

> 请读取 `skills/financial-statement-visuals/SKILL.md`，用 prepare → 官方缺口研究 → build 为 COST 生成单公司 HTML；保留来源、实际财年与缺项。

无需先安装全局 Skill。若复制安装到其他 Skill 环境，复制完整目录及 references，并另行提供本仓库源码位置。项目文档应从已经定位的项目根目录读取，不按 Skill 安装位置推断。

prepare 获取并整理资料，但不自行调用模型。AI 在当前环境中补读官方原文，按 [工作流契约](report-v2.md) 写 supplements.json；固定程序核验并计算，不执行模型提供的代码或坐标。没有额外模型 API 配置，不使用 FutuMCP。

公开测试使用合成资料；另附三个 [官方来源示例](../examples/README.md)，供离线体验。示例不是取数缓存，也不应当作新年度的补充来源。资料不足允许部分报告；交付需说明数据截止、核验范围和可比性，不能把成功构建当作完整财务审计。
