# -*- coding: utf-8 -*-
"""生成 docs/项目上线交付运行手册.docx"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docx_kit import Doc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "项目上线交付运行手册.docx"


def main():
    d = Doc(
        "项目上线交付运行手册",
        "山海旅居 · 房态与入住协同 MVP：部署、验收、运维与故障处置",
        [
            "系统版本：room-status-mvp v0.1.0　文档版本：V1.0",
            "编制日期：2026 年 11 月 6 日　适用对象：门店 IT、值班经理、运营管理员",
            "配套文档：《需求分析方案》《项目设计方案》《测试方案》《docs/部署地址.md》",
        ],
        footer_note="山海旅居 · 运行手册 V1.0",
    )

    d.h1("一、适用范围与交付物")
    d.p("本手册面向接管系统的门店 IT 与运营管理员，覆盖从「拿到代码」到「稳定跑一周」的全过程："
        "环境准备、部署、初始化、上线检查、日常巡检、备份恢复、故障处置、升级回滚与培训交接。"
        "按本手册执行，一名熟悉 Linux 与命令行的工程师可在 60 分钟内完成首次上线。")
    d.table(
        ["类别", "交付物", "位置"],
        [
            ["可运行系统", "房态与入住协同 MVP（FastAPI + SQLite + 原生前端）", "src/room-status-mvp/"],
            ["工程文档", "系统说明书（入口、账号、验收路径、接口清单）", "src/room-status-mvp/README.md"],
            ["架构文档", "分层、状态机、Agent 三段式、知识库选型、演进", "src/room-status-mvp/docs/ARCHITECTURE.md"],
            ["制度知识库", "5 篇制度（口径 / 查房 / 闸门 / 升级 / 异常）", "src/room-status-mvp/kb/docs/"],
            ["需求与方案", "需求分析方案、项目设计方案（含报价与投入产出）", "docs/"],
            ["测试材料", "测试方案 + 五份场景测试过程记录", "docs/测试/"],
            ["本手册", "上线交付运行手册", "docs/项目上线交付运行手册.docx"],
        ],
        caption="表 1　交付物清单",
        widths=(2.6, 8.4, 4.8),
    )

    d.h1("二、环境要求")
    d.table(
        ["项目", "最低要求", "说明"],
        [
            ["操作系统", "Windows 10/11 或 Linux（x86_64）", "开发验证在 Windows 11 完成，生产建议 Linux"],
            ["Python", "3.10 及以上", "3.12 实测通过；依赖见 requirements.txt"],
            ["内存 / 磁盘", "2 GB / 5 GB 可用空间", "数据库单文件增长，1 万条事件约 2 MB"],
            ["端口", "8100（默认，可改）", "需与门店现有系统不冲突"],
            ["浏览器", "Chrome / Edge 最近两个大版本", "页面无构建步骤，无需 Node"],
            ["网络", "内网即可运行；模型调用需出网", "不配模型密钥时助手降级为规则模式，功能完整"],
            ["数据源", "本期为本地演示库，不接 PMS", "接 PMS 为二期，替换点见架构文档 §5.3"],
        ],
        caption="表 2　环境要求",
        widths=(3.0, 5.4, 7.4),
    )
    d.note("门店若不希望调用外部模型，直接跳过 LLM_API_KEY 即可。此时助手用规则规划器回答，"
           "房态、闸门、交接、审计全部可用，仅话术不如模型自然。", label="可选")

    d.h1("三、部署")
    d.h2("3.1 方式一：单机快速启动（试点推荐）")
    d.p("适用于门店一台常开机器或现有服务器。装完依赖即可运行，数据落本地 SQLite。")
    d.code("""# 1) 取代码
git clone <repo> && cd HRSC/src/room-status-mvp

# 2) 安装依赖（建议建虚拟环境）
python -m venv .venv
.venv\\Scripts\\activate          # Linux: source .venv/bin/activate
pip install -r requirements.txt

# 3) 配置
cp .env.example .env             # 填 LLM_API_KEY（可留空）与 JWT_SECRET（必须改）

# 4) 启动（首次启动自动建库并写入演示数据）
python -m uvicorn app:app --host 0.0.0.0 --port 8100

# 5) 验证
curl http://127.0.0.1:8100/healthz""")
    d.h2("3.2 方式二：托管为常驻服务")
    d.p("Linux 用 systemd 托管，实现开机自起与崩溃拉起；Windows 可用「任务计划程序」以「系统启动时」触发同一命令。")
    d.code("""# /etc/systemd/system/hotel-mvp.service
[Unit]
Description=Hotel Room-Status MVP
After=network.target

[Service]
WorkingDirectory=/opt/hotel-mvp
Environment="PATH=/opt/hotel-mvp/.venv/bin"
ExecStart=/opt/hotel-mvp/.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8100
Restart=always
RestartSec=5
User=hotel

[Install]
WantedBy=multi-user.target""")
    d.code("""sudo systemctl daemon-reload
sudo systemctl enable --now hotel-mvp
sudo systemctl status hotel-mvp --no-pager
journalctl -u hotel-mvp -n 50 --no-pager   # 看日志""")
    d.h2("3.3 配置项")
    d.table(
        ["变量", "必填", "默认", "说明"],
        [
            ["LLM_BASE_URL", "否", "阿里云百炼兼容地址", "OpenAI 兼容网关地址"],
            ["LLM_API_KEY", "否", "空", "留空则助手降级为规则模式（功能完整）"],
            ["LLM_MODEL", "否", "qwen-plus", "生成模型；换模型只需改这一项"],
            ["LLM_TIMEOUT", "否", "45", "单次调用超时（秒）"],
            ["JWT_SECRET", "是", "示例值", "**上线必须改成 32 位以上随机串**，否则登录态可被伪造"],
            ["HOST / PORT", "否", "127.0.0.1 / 8100", "生产建议 0.0.0.0 + 反向代理"],
            ["HOTEL_NAME", "否", "山海旅居", "页面标题显示名"],
        ],
        caption="表 3　配置项说明（.env）",
        widths=(3.6, 1.6, 4.2, 6.4),
    )
    d.code("""# 生成 JWT_SECRET（任选其一）
python -c "import secrets;print(secrets.token_urlsafe(48))"
openssl rand -base64 48""")

    d.h1("四、首次初始化与账号")
    d.p("首次启动会自动建库（14 张表）并写入演示数据：24 间房、7 个房态的当前快照、近 7 天房态流水、"
        "5 篇制度、4 个账号。演示数据可在正式试点前清空重播。")
    d.table(
        ["账号", "口令", "岗位", "能做什么", "刻意不能做什么"],
        [
            ["admin", "Admin@123", "运营管理", "全部功能 + 知识库、阈值、账号、审计", "—"],
            ["front", "Front@123", "前台", "看板、办入住/退房、报修、交接班", "不能下查房结论、不能自己置可售"],
            ["qa", "Qa@123", "质检", "发起查房、查房通过/不通过、返工", "不能办入住"],
            ["house", "House@123", "客房", "开始清扫、提交已清扫、报修、维修完成", "不能下查房结论"],
        ],
        caption="表 4　初始账号与权限边界",
        widths=(1.8, 2.2, 2.0, 6.0, 4.6),
    )
    d.note("上线第一件事：用 admin 登录 →「账号」→ 逐个「重置口令」，把演示口令全部换掉。"
           "系统不提供弱口令检查，这一步必须人工做。", label="必做")
    d.h3("4.1 演示数据与正式数据")
    d.p("演示数据用于验收演示，不代表真实客人。正式试点前，确认 data/mvp.db 的处理方式："
        "① 保留演示数据（适合先培训）；② 重建空库（删除 data/mvp.db 后重启，自动建表但不写演示数据）。"
        "两种方式都要在交接单上写明，避免验收时把演练数据当真实数据。")

    d.h1("五、上线检查清单")
    d.p("以下 12 项全部通过方可视为「上线成功」。每项都有可执行的验证命令或页面动作，建议逐项打勾并留截图。")
    d.table(
        ["#", "检查项", "操作 / 命令", "通过标准"],
        [
            ["1", "服务存活", "curl /healthz", "返回 status=ok，rooms=24"],
            ["2", "模型状态", "同上，看 llm_ready", "有 Key 为 true；无 Key 为 false 且 mode=fallback 可用"],
            ["3", "数据库可写", "办一次入住再退房", "房态变化且 room_events 新增两条"],
            ["4", "四账号登录", "front / qa / house / admin", "各自进入对应页面，无 403"],
            ["5", "岗位隔离", "front 调 pass_inspection", "返回 40301「仅限…」"],
            ["6", "入住闸门", "对已清扫房查闸门", "allowed=false，给出原因与替代房"],
            ["7", "查房守卫", "六项未全勾时提交通过", "被拒绝，提示未通过的检查项"],
            ["8", "知识库", "管理端改一段口径后提问", "回答按新口径，引用指向该文档"],
            ["9", "助手提案", "对助手说「帮我给 1103 发起查房」", "生成待确认卡片，确认前房态不变"],
            ["10", "审计", "管理端「审计」", "能看到上述操作记录"],
            ["11", "备份", "执行备份命令", "备份文件可打开，表数量一致"],
            ["12", "页面性能", "看板首屏", "≤ 2 秒（本地）"],
        ],
        caption="表 5　上线检查清单（12 项）",
        widths=(0.9, 3.2, 6.4, 5.5),
    )

    d.h1("六、日常运行与巡检")
    d.h2("6.1 每日巡检（5 分钟）")
    d.table(
        ["时间", "动作", "看什么", "异常动作"],
        [
            ["开班前", "打开管理端概览", "超时房间数、可售率", "超时 > 6 间：通知质检与客房调度"],
            ["开班前", "看板核对", "维修房与可售房是否与实际一致", "不一致：走「异常处置」流程第 9.6 节"],
            ["班中", "看助手统计", "guarded 占比", "> 15%：检查提示词或知识库是否缺条目"],
            ["交班", "生成交接单", "待查房、维修、在住、未完成任务", "必须具名签收后才算交接完成"],
            ["收班", "执行备份", "备份文件大小与时间", "失败：当日必须补做并记录"],
        ],
        caption="表 6　日常巡检表",
        widths=(2.0, 3.4, 5.6, 5.0),
    )
    d.h2("6.2 关键指标与阈值")
    d.table(
        ["指标", "计算方式", "警戒线", "含义"],
        [
            ["已清扫→可售均时", "room_events 中 clean→ready 的耗时均值", "> 45 分钟", "查房环节积压"],
            ["P90 同上", "同上第 90 百分位", "> 60 分钟", "长尾拖慢高峰"],
            ["待查房超时数", "state=clean 且超阈值（默认 12 分钟）", "> 5 间", "需临时加派质检"],
            ["闸门拦截次数", "interventions 计数", "周同比上升", "口径培训不足或房源紧张"],
            ["助手护栏触发率", "mode=guarded / 总对话", "> 15%", "提示词或知识库需维护"],
            ["提案采纳率", "confirmed / (confirmed+rejected)", "< 60%", "助手建议与实际不符"],
        ],
        caption="表 7　关键运行指标",
        widths=(3.4, 6.4, 2.4, 4.0),
    )
    d.h2("6.3 日志与留存")
    d.bullets([
        "应用日志：uvicorn 标准输出（systemd 下用 journalctl -u hotel-mvp 查看），建议保留 30 天；",
        "业务流水：room_events、interventions、audit_log 只追加不删除，是验收与追责的唯一凭据；",
        "隐私：日志与页面不记录客人手机号、证件号；客人姓名仅用于入住登记，导出时需脱敏。",
    ])

    d.h1("七、备份与恢复")
    d.h2("7.1 备份策略")
    d.p("SQLite 单文件，备份即复制。生产环境必须用 `.backup` 命令而非直接 `cp`，避免复制到写入中的页。")
    d.code("""# 在线备份（推荐，不锁库）
sqlite3 data/mvp.db ".backup 'backup/mvp-$(date +%Y%m%d-%H%M).db'"

# 校验：能打开且表数量为 14
sqlite3 backup/mvp-20261106-2200.db "select count(*) from sqlite_master where type='table';"

# Windows 等价（PowerShell）
Copy-Item data\\mvp.db ("backup\\mvp-" + (Get-Date -Format yyyyMMdd-HHmm) + ".db")""")
    d.table(
        ["项目", "策略", "说明"],
        [
            ["频率", "每日收班 1 次 + 每周全量 1 次", "可用计划任务自动执行"],
            ["保留", "日备 14 天、周备 8 周", "按门店合规要求可延长"],
            ["异地", "每周周备复制到 NAS 或对象存储", "防单机故障"],
            ["RPO", "≤ 24 小时", "日备间隔"],
            ["RTO", "≤ 30 分钟", "替换文件 + 重启服务"],
        ],
        caption="表 8　备份策略",
        widths=(2.4, 6.6, 6.8),
    )
    d.h2("7.2 恢复演练（每季度一次）")
    d.code("""# 1) 停服务
sudo systemctl stop hotel-mvp
# 2) 保留现场
mv data/mvp.db data/mvp.db.bad-$(date +%s)
# 3) 还原
cp backup/mvp-20261106-2200.db data/mvp.db
# 4) 启动并校验
sudo systemctl start hotel-mvp
curl -s http://127.0.0.1:8100/healthz""")
    d.note("恢复后必须抽查三件事：① 24 间房都在；② 最近一条 room_events 时间符合预期；"
           "③ 用 front 登录能正常办一次入住。三项都对才算恢复成功，并在演练记录上签字。", label="必做")

    d.h1("八、故障处置手册")
    d.p("下表覆盖试点期最常见的问题。每条都给出「现象 → 判断 → 处置」，值班人员可按表操作，无需读代码。")
    d.table(
        ["#", "现象", "可能原因", "处置"],
        [
            ["1", "页面打不开（连接被拒绝）", "进程退出 / 端口被占", "查进程与端口，重启服务；端口冲突改 PORT"],
            ["2", "/healthz 正常但页面 500", "模板或静态文件缺失", "核对 templates/、static/ 是否完整；看日志 trace"],
            ["3", "登录成功但立刻跳回登录页", "JWT_SECRET 变更", "统一 .env 的 JWT_SECRET 后重启，全员重新登录"],
            ["4", "助手回答「规则模式」", "未配 Key / Key 失效 / 超时", "查 llm_ready；核对 Key 与出网；不影响房态功能"],
            ["5", "助手给出的数字与看板不一致", "模型幻觉被护栏拦下", "看响应 note（guarded）；必要时在知识库补条目"],
            ["6", "写操作报「数据库繁忙」", "并发写锁 / 磁盘满", "查磁盘；SQLite 重试；长期需换 PostgreSQL"],
            ["7", "知识库检索为空", "文档被删 / 索引未重建", "管理端「重建索引」；确认 kb_docs 有记录"],
            ["8", "房态与实际不符", "人为误改 / 未按流程", "管理端审计查操作人；按「返工」纠正并留原因"],
            ["9", "时间显示差 8 小时", "服务器时区非 Asia/Shanghai", "设置时区后重启，核对历史事件时间"],
            ["10", "交接单内容为空", "当日无待办 / 数据未刷新", "手动刷新；确认 tasks 表有 open 记录"],
        ],
        caption="表 9　常见故障与处置",
        widths=(0.8, 4.4, 4.2, 6.6),
    )
    d.h2("8.1 三个必须上报的情况")
    d.bullets([
        "**闸门未拦截**：任何一次「已清扫但未查房」的房间被成功办理入住，立即上报（这是红线，f04）；",
        "**审计缺记录**：关键操作在审计页查不到，说明写入链路异常，需停止演示并排查；",
        "**数据不一致**：看板可售数与实际可售房差异 ≥ 2 间，且刷新后仍不一致。",
    ])

    d.h1("九、升级与回滚")
    d.table(
        ["步骤", "动作", "校验"],
        [
            ["1", "备份当前库与 .env", "备份文件存在且可打开"],
            ["2", "拉取新代码，保留 .env 与 data/", "git status 干净"],
            ["3", "pip install -r requirements.txt", "无报错"],
            ["4", "重启服务", "/healthz 返回 ok，页数/表数正常"],
            ["5", "跑一遍上线检查清单 12 项", "全部通过"],
            ["6", "异常时回滚：git checkout <上一个 tag> + 还原备份", "旧版本可登录、数据完整"],
        ],
        caption="表 10　升级与回滚流程",
        widths=(1.2, 9.0, 5.6),
    )
    d.note("升级窗口安排在非高峰（建议 15:00–16:00），避开 18:00–21:00 入住高峰。"
           "升级期间前台按「纸面登记 + 事后补录」降级，补录必须当日完成并核对。", label="窗口")

    d.h1("十、安全与合规")
    d.bullets([
        "**密钥**：.env 不入库、不截图、不发群；JWT_SECRET 上线前必须替换；离职人员当日禁用账号；",
        "**账号**：一人一号，不共用；门店 IT 保留 admin，运营管理员保留一个 admin 账号用于审计复核；",
        "**日志隐私**：不记录手机号、证件号；导出数据前脱敏；影像留存按门店规则执行（90 天待定，f43）；",
        "**审计**：房态变更、提案确认、知识库修改、账号操作全部留痕，保留期不少于验收周期 + 6 个月；",
        "**边界**：系统只读核对与人工交接，不写回 PMS、不自动放行、不替代质检结论（红线 f04）。",
    ])

    d.h1("十一、培训与交接")
    d.table(
        ["对象", "内容", "时长", "考核方式"],
        [
            ["前台", "看板、入住闸门、交接班、助手提问", "60 分钟", "现场办一次「被拦截 → 换房 → 成功入住」"],
            ["质检", "查房队列、六项检查、返工", "45 分钟", "完成一次通过 + 一次不通过"],
            ["客房", "清扫回写、报修、维修完成", "45 分钟", "完成一次 dirty→clean 与一次报修"],
            ["运营管理", "知识库维护、阈值、审计、账号", "90 分钟", "改一条口径并验证助手回答随之变化"],
        ],
        caption="表 11　培训与考核",
        widths=(2.4, 6.4, 2.2, 4.8),
    )
    d.h2("11.1 交接签字")
    d.table(
        ["角色", "签什么", "不签的后果"],
        [
            ["运营经理", "业务结果与试点范围", "范围无法冻结，验收标准会被反复修改"],
            ["服务质量专员", "质量红线与审计口径", "上线后风险无人背书"],
            ["PMS 工程师 / IT", "技术可行性、备份与恢复", "故障时无人兜底"],
        ],
        caption="表 12　三签表",
        widths=(3.2, 6.0, 6.8),
    )
    d.p("三方签字页建议与本手册一起归档，作为上线交付的凭证。签字后如需变更范围，走变更单，不在群内口头确认。")

    d.h1("十二、附录")
    d.h2("12.1 常用命令")
    d.code("""# 健康检查
curl -s http://127.0.0.1:8100/healthz

# 重启（systemd）
sudo systemctl restart hotel-mvp

# 看最近日志
journalctl -u hotel-mvp -n 100 --no-pager

# 备份
sqlite3 data/mvp.db ".backup 'backup/mvp-$(date +%Y%m%d-%H%M).db'"

# 跑测试（不需要模型密钥）
python -m unittest discover -s tests -v""")
    d.h2("12.2 接口速查")
    d.table(
        ["分组", "端点", "用途"],
        [
            ["认证", "POST /api/auth/login | logout | GET /me", "登录与身份"],
            ["房态", "GET /api/rooms | /api/rooms/{no}", "看板与单房详情"],
            ["迁移", "POST /api/rooms/{no}/transition", "唯一写房态入口"],
            ["入住", "GET /api/checkin/gate | POST /api/rooms/{no}/checkin", "闸门与入住"],
            ["助手", "POST /api/agent/chat | POST /api/agent/actions/{id}/confirm", "对话与提案确认"],
            ["知识库", "GET/POST/DELETE /api/kb/docs | POST /api/kb/reindex", "制度维护"],
            ["管理", "/api/admin/audit | settings | users | agent-stats", "审计与配置"],
        ],
        caption="表 13　接口分组速查（完整 34 个见 README）",
        widths=(2.2, 8.4, 5.2),
    )
    d.h2("12.3 联系与升级路径")
    d.table(
        ["层级", "谁", "什么时候找"],
        [
            ["一线", "值班经理", "页面异常、房态不一致但系统可用"],
            ["二线", "门店 IT", "服务重启、备份恢复、账号问题"],
            ["三线", "交付方（本项目组）", "数据损坏、红线事件、需要改代码"],
        ],
        caption="表 14　问题升级路径",
        widths=(2.4, 5.2, 8.4),
    )
    d.note("本手册中的页面地址、账号与命令均以当前版本（v0.1.0）为准。上线地址见 docs/部署地址.md；"
           "若门店改为内网部署，以门店实际地址替换。", label="版本")

    path = d.save(OUT)
    print("saved", path)


if __name__ == "__main__":
    main()
