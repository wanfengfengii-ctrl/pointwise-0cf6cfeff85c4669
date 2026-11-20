# 跨工装通流复核

现有 `README.md` 说明本地工装的登记、原测、勘误、冻结和固定夹持报告。新增复核使用两份先发行、后接纳的端子件，核算稳态纯电阻回路。站库和中心库可各自独立初始化。交班时中心只持有接纳件与本次请求。

## Python 入口

| 入口 | 输入 | 返回 |
| --- | --- | --- |
| `revision.freeze.export_terminal_piece(db, freeze_id, terminals)` | 站库连接、确切冻结号及非空有序互异的已登记公共端子名 | 固定端子件的 UTF-8 JSON `bytes` |
| `report.issue.accept_terminal_piece(db, payload)` | 中心库连接、端子件 `bytes` | 已接纳件的正整数编号 |
| `report.issue.issue_coupled(db, piece_ids, jumper_rows, injection_rows)` | 中心库连接、按工装顺序给出的两个已接纳件编号、跳线行和注流行 | 固定复核报告，含 `report_id`、`body` 和 `receipt` |
| `report.read.read_coupled(db, report_id)` | 中心库连接、复核报告号 | 同一固定复核报告 |

所有库继续用 `lab.connect` 和 `lab.initialize` 打开和初始化，沿用 V1 的连接与写事务约定。原 V1 报告仍通过原入口签发、领读和导出。复核报告号由复核入口解释。

## 端子件与接纳

端子件的顶层字段为 `version`、`experiment`、`bench_name`、`revision_id`、`freeze_id`、`terminals`、`response`。`version` 为整数 2。试验和工装名沿用原登记，有序端子数组沿用发行请求，两个来源编号取自确切冻结。相同发行输入应得到固定件。不同站库的本地工装、修订和冻结编号可以相同，中心以同一试验内的工装名区分工装。

`response` 的表示由实现决定。它须精确对应同一冻结修订上所选端子的完整共同响应，包含所选端子所属的导通分岛。所选端子取任意有理电位时，站件应足以确定这些端子的净供流和该工装的总耗散。未选节点在站内服从净注流为零，完全没有所选端子的分岛耗散为零。未选节点、内部支路及原测明细留站。

中心持久接纳固定字节。坏件包括非 UTF-8 JSON、异版本、缺失或非法的来源字段、空或重复端子、端子覆盖与响应不符、响应无法解码或不能表示所列端子的被动无接地电阻网络。坏件和 V1 报告字节报 `ValueError`，接纳失败无新增。发行使用未知冻结号、重复或非登记端子也报 `ValueError`。

## 当班请求与报告

`piece_ids` 按左、右顺序选择同试验、不同工装的两件。端点为 `[槽位, 端子名]`，槽位是非布尔整数 0 或 1，只能引用对应件列明的端子。两件中相同的端子名各在自己的槽位解释。

跳线行按 `[跳线名, 首端, 末端, 电导]` 给出。跳线名非空且唯一，首末端必须跨槽位，可以有多根跳线连接同一对端点。电导非负，单位 S。零电导保留在请求及结果序位。注流行按 `[端点, 注流]` 给出，每端点至多出现一次，单位 A，正值表示流入工装，未列端点为零。跳线或注流清单可以为空。序列可用元组或列表，数值沿用 V1 的整数或有理数文本，布尔和浮点数非法。未知或不匹配的选件及非法请求报 `ValueError`。

合成分量由站内导通关系及本次正电导跳线共同决定。只有每一分量净注流均为零才可行。可行时每个节点遵守净流平衡，跳线电流为其电导乘首末电位差，分站耗散只计该站原工装的耗散。整体电位平移不改变结果。断开的跳线电流为精确零。合法但不可行的请求照常签发。

报告 `body` 为字典，含 `version`（整数 2）、`report_id`、`experiment`、`pieces`、`jumpers`、`injections`、`feasible`、`jumper_currents` 和 `dissipation`。`pieces` 为选件原序列表，每项含 `piece_id`、`bench_name`、`revision_id`、`freeze_id`、`terminals` 和原件字节的 `sha256`。`jumpers`、`injections` 按原请求顺序存为列表行，端点存为列表，电导和注流规范成 `Fraction`。`feasible` 为布尔值。可行时 `jumper_currents` 按跳线顺序、`dissipation` 按选件顺序各为 `Fraction` 列表，单位分别为 A 和 W。不可行时两字段均为 `None`。`receipt` 含 `version`、`report_id` 和 `body_sha256`，正文摘要沿用 V1 的 `report.codec.encode_report` 编码规则。

正文与回执同次提交。SQLite 提交失败传播原异常且无新增报告或回执，原请求可重试。更正原测及重开中心库后按复核报告号读取存值。未知复核报告号报 `KeyError`。

## 联动样例与运行

`examples/coupled_shift.json` 提供独立两站、注流及三份跳线设置。`coupled_sample.py` 的 `load_sample()` 读取样例，`seed_station(db, experiment, station)` 用 V1 入口登记并返回 `(bench_id, revision_id, freeze_id)`。命令 `python3 -B coupled_sample.py` 核对该样例的 V1 原测与勘误。甲站原两段电导各为 2 S，乙站 c 为孤端。关闭站库后，以下为中心应签出的结果。

| 当班请求 | 可行 | 跳线电流 A | 甲、乙工装耗散 W |
| --- | --- | --- | --- |
| `closed` 与样例注流 | 是 | `[1]` | `[1, 0]` |
| `open` 与样例注流 | 否 | `None` | `None` |
| `parallel` 与样例注流 | 是 | `[1/2, -1/2]` | `[1, 0]` |
| `open` 与空注流 | 是 | `[0]` | `[0, 0]` |
| 无跳线，甲 d 注入 1 A、乙 d 注入 −1 A | 否 | `None` | `None` |

用甲站勘误后的冻结重新发行，仍以 `closed` 及样例注流复核，甲站耗散为 `2/3` W，原报告仍领到 `1` W。另可用三端联动手算核对共同响应。把甲的 a、b、d 分别经 1 S 支路接到同一私有节点，乙 c 仍为孤端。b→c、d→c 各接 1 S，a 注入 1 A，c 注入 −1 A。两根跳线依次为 `1/2`、`1/2` A，甲乙耗散为 `3/2`、`0` W。

保留 `python3 -B check_project.py` 运行完整 V1 回归及 `python3 -B demo.py` 的本地成果演示。沿 `.pointwise-runtime.json` 的 `verify` 核对原回归和跨工装链路，参加核验的检查失败时应返回非零退出码。沿 `demo` 展示同一对件在关闭源库后的接通和开路裁决，以及重开中心后的固定报告。
