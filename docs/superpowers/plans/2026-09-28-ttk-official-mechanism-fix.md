# TTK 官方机制审计修复 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复审计报告(docs/audit/2026-09-28-ttk-official-mechanism-audit-report.md)的 P0/P1/P2:81 点 E[N] 与官方样本脱节收敛到逐位级、文档虚假声明统一为实测口径、验证基础设施固化到 CI。

**Architecture:** 同步器从「3 情景硬编码验证样本」改为「官方 index 全量情景」→ 重新同步入库全量 candidateMetrics → 用 tools 验证工具重算全部样本定位偏差 → 按诊断结论修反解逻辑或走 overrides → 固化回归测试与 CI → 重算榜单 → 统一文档口径。

**Tech Stack:** Python 3.13(managed),运行期零第三方依赖(标准库);pytest 仅测试;上游 dfttk.com/data/v3。

## Global Constraints

- 运行期零第三方依赖:采集与引擎全部标准库(urllib/json/dataclasses);pytest/pytest-cov 仅测试(requirements.txt 现状)。
- Python 解释器:`C:\Users\pc\.workbuddy\binaries\python\versions\3.13.12\python.exe`(下称 PY);测试用 venv:`C:\Users\pc\.workbuddy\binaries\python\envs\default`(Task 1 创建,装 `requirements.txt`)。下述 `pytest` 命令均指 `C:\Users\pc\.workbuddy\binaries\python\envs\default\Scripts\python.exe -m pytest`。
- 数据文件 `data/game/*` 保持上游原名,勿重命名;`data/game/weapons.json` 等 verify_status=derived 的文件由 packs 反解而来。
- 上游版本策略:重新同步后若上游 `dataset_version` > `20260911-044903.3`,**以新版本为准**做全量验证;provenance.json 由同步器自动更新。
- TTK 口径不变:`TTK = (E[N] − 1) × 射击间隔`,四项排除(开镜/初速/换弹/命中率)不动。
- 收敛目标:全部官方样本 |Δ| ≤ 1e-9;确因上游数据内部矛盾无法归零的点,记录最小残差与理由到 provenance.integrity,并在报告中说明。
- 不保留向后兼容:过时表述直接改,不留兼容层。
- 每个任务结束:验证通过 → `git add <本任务文件> && git commit`(不 push)。

---

### Task 1: 全情景验证样本入库(同步器改造 + 重新同步)

**Files:**
- Modify: `src/collectors/game_data_sync.py:1071-1075`(`VALIDATION_SCENARIO_IDS`)与 `:1109-1115`(下载循环)
- Regenerate: `data/game/validation_samples.json`、`data/game/provenance.json`(同步器自动)

**Interfaces:**
- Consumes: `normalize_ranking_index(ranking_index)["scenarios"]`(每项含 `scenario_id`、`file`,见 game_data_sync.py:1000-1012)。
- Produces: `validation_samples.json` 含官方 index 全部情景(预期 21 个);Task 2 的验证工具与 Task 4 的收敛复验都消费该文件。

- [ ] **Step 1: 探查情景文件路径模式**

先看本地缓存,再必要时下载:

```bash
cd "E:/WK/日常" && ls .cache/dfttk/ | grep -i ranking
"C:/Users/pc/.workbuddy/binaries/python/versions/3.13.12/python.exe" -c "
import json
idx = json.load(open('.cache/dfttk/rankings__firefight__index.json', encoding='utf-8'))
sc = idx.get('scenarios') or []
print('scenario count:', len(sc))
for s in sc[:25]:
    print(s.get('id'), '| file=', s.get('file'), '| defense=', s.get('defensePresetKey'), s.get('ammoLevel'), s.get('probabilityPresetKey'))
print('dynamicInputs:', idx.get('dynamicInputs'))
"
```

判定:`file` 字段是否含子路径(如 `dynamic/xxx.json`)。若缓存无 index 文件,直接 `python -c "import urllib.request; print(urllib.request.urlopen('https://dfttk.com/data/v3/rankings/firefight/index.json').read().decode()[:2000])"` 探查。
**分支:** 路径 = `rankings/firefight/{file or scenario_id}.json`;`file` 缺失时回退 `{scenario_id}.json`。

- [ ] **Step 2: 修改同步器为全量情景**

删除 `VALIDATION_SCENARIO_IDS` 常量(game_data_sync.py:1071-1075),把 sync_all 中的验证情景下载(1109-1115 行)改为基于 `ranking["scenarios"]` 动态全量——注意 `ranking = normalize_ranking_index(ranking_index)` 目前在 1129 行,**需将下载循环移到该行之后**(或直接遍历原始 `ranking_index` 的 scenarios 数组):

```python
    ranking = normalize_ranking_index(ranking_index)

    # 验证样本:官方 index 全量情景(不遗漏任何带 candidateMetrics 的情景)
    validation_scenarios: Dict[str, Dict[str, Any]] = {}
    for scenario in ranking["scenarios"]:
        sid = scenario["scenario_id"]
        rel = scenario.get("file") or f"{sid}.json"
        try:
            payload, _ = _download_json(f"rankings/firefight/{rel}", cache_dir, refresh=refresh)
            validation_scenarios[sid] = payload
        except SourceUnavailable as exc:  # pragma: no cover - 网络分支
            logger.warning("验证情景 %s 获取失败:%s", sid, exc)
```

同时在同步摘要(函数返回的 summary dict)中记录 `validation_scenario_count` 与 `validation_sample_points`(候选×距离点总数),便于验收。

- [ ] **Step 3: 重跑同步**

```bash
cd "E:/WK/日常" && "C:/Users/pc/.workbuddy/binaries/python/versions/3.13.12/python.exe" -m src.collectors.game_data_sync
```

Expected: 正常退出;`data/game/validation_samples.json` 情景数 = 官方 index 情景数(预期 21);`provenance.json` 的 `source.dataset_version` 与 `outputs["validation_samples.json"]` 哈希已更新。记录:新 dataset_version、情景数、候选总数、样本(距离点)总数(预期 ≈3774)。

- [ ] **Step 4: 验证数据自洽**

```bash
"C:/Users/pc/.workbuddy/binaries/python/versions/3.13.12/python.exe" -c "
import json
v = json.load(open('data/game/validation_samples.json', encoding='utf-8'))['samples']
print('scenarios:', len(v))
print('candidates:', sum(len(x['candidate_metrics']) for x in v.values()))
print('points:', sum(len(pts) for x in v.values() for _, pts in x['candidate_metrics']))
"
```

Expected: scenarios=21(或 index 实际数)、points ≥ 3000。若某情景 candidateMetrics 为空被跳过(normalize_validation_samples 的 `if not metrics: continue`),如实记录跳过清单。

- [ ] **Step 5: Commit**

```bash
cd "E:/WK/日常" && git add src/collectors/game_data_sync.py data/game/validation_samples.json data/game/provenance.json
git commit -m "feat(sync): 验证样本扩为官方 index 全量情景(审计 P0 修复第一步)"
```

---

### Task 2: 全量官方复现验证工具(修复前基线)

**Files:**
- Create: `tools/verify_official_reproduction.py`(模式参照 `tools/crosscheck_third_party.py`:独立工具、标准库、退出码 0/1)

**Interfaces:**
- Consumes: `data/game/validation_samples.json`(Task 1 产物);引擎 `load_game_data`、`WeaponStateResolver`、`build_context_from_state`(用法同 tests/test_ballistics.py:159-174 的端到端范式)。
- Produces: 控制台分级精度统计 + 偏差明细 JSON(`--report` 指定路径,Task 3/4 消费);退出码 0=全部 |Δ|≤tol,1=存在超差点。

- [ ] **Step 1: 实现验证工具**

候选 id 形如 `18010000001:base:37100400001:2=13020000349`(= `weapon_id:profile_key:ammo_id:slot=part...`),解析规则:前 3 段为 weapon/profile/ammo,其余 `slot=part` 为 loadout;`WeaponStateResolver.resolve(weapon_id:profile_key, loadout=dict)`。核心结构:

```python
"""官方 candidateMetrics 全量复现验证。
用法:
    python tools/verify_official_reproduction.py                 # 汇总到 stdout
    python tools/verify_official_reproduction.py --tol 1e-9 --report .probe/repro.json
退出码:0=全部达标;1=存在超差。
"""
# 伪骨架(实现必须完整,不留 TODO):
# 1. gd = load_game_data("data/game");resolver = WeaponStateResolver(gd)
# 2. samples = json.load(validation_samples.json)["samples"]
# 3. for sid, s in samples.items():
#      armor_def = s["scenario"]["defense"]  # 或经 engagement.scenario_armor 组装
#      probs = s["scenario"]["hit_probabilities"]
#      for cand_id, points in s["candidate_metrics"].items():
#        weapon, profile, ammo_id, loadout = parse_candidate(cand_id)
#        state = resolver.resolve(f"{weapon}:{profile}", loadout=loadout)
#        for dist, official in points:
#          ctx = build_context_from_state(state, gd.get_ammo(ammo_id), armor_def, probs, float(dist), armor_level=防御等级)
#          got = ctx.expected_kill_shots();delta = abs(got - official)
#    4. 分级统计:d==0 / ≤1e-9 / ≤1e-5 / ≤1e-2 / >1e-2,最大 |Δ| 及其 (sid, cand, dist)
#    5. --report 时写 {"summary": {...}, "deviations": [{...} |Δ|>tol 全量]}
```

护甲组装注意:情景自带的 `defense` 是官方 preset(耐久可能低于 max),优先用样本内 `defense` 字段的 `maxDurability`/`coveredHitAreas`,不要用 armor.json 默认值覆盖(参照 engagement.py:85-95 `scenario_armor` 的覆盖逻辑;level 字段取 defense.armor.level)。

- [ ] **Step 2: 跑出修复前基线**

```bash
cd "E:/WK/日常" && mkdir -p .probe && "C:/Users/pc/.workbuddy/binaries/python/versions/3.13.12/python.exe" tools/verify_official_reproduction.py --tol 1e-9 --report .probe/repro-baseline.json
```

Expected: 退出码 1(存在偏差,即审计发现的 81 点及可能的新增点);stdout 有完整分级统计。**记录基线数字**(逐位数/1e-9 内数/>1e-2 数/最大偏差)。若单次全量 >5 分钟,工具需支持 `--scenario` 过滤先行验证,全量转后台跑。

- [ ] **Step 3: Commit**

```bash
cd "E:/WK/日常" && git add tools/verify_official_reproduction.py
git commit -m "feat(tools): 官方 candidateMetrics 全量复现验证工具"
```

---

### Task 3: 偏差根因诊断(只读分析)

**Files:**
- Read-only: `.probe/repro-baseline.json`、`src/collectors/game_data_sync.py`(normalize_weapon 的 falloff/damage 反解段)、`src/engine/weapon_state.py`(falloff_rate :328-336、节拍 :595-630、attr2 缩放 :657-668)、`.cache/dfttk/packs__*`、`data/game/weapons.json`

**Interfaces:**
- Consumes: Task 2 的偏差明细。
- Produces: 根因结论(下方三类之一,附逐武器证据表),Task 4 按结论分支执行。

- [ ] **Step 1: 汇总偏差武器清单**

从 `.probe/repro-baseline.json` 的 deviations 提取 weapon_id 去重列表,按武器类型聚合(SMG/AR/其他),标注失败距离点模式(0m/26m/61m 全灭 vs 个别点)。

- [ ] **Step 2: 逐类对照上游 packs**

对每把偏差武器:
1. 取上游原始 packs:`.cache/dfttk/packs__combat__weapons__{weapon_id}.json` 与 `packs__build__weapons__{weapon_id}.json`(缓存缺失时用 urllib 从 `https://dfttk.com/data/v3/packs/...` 下载到 `.probe/`);
2. 与 `data/game/weapons.json` 对应记录的 `damage_profile`(base_damage/base_armor_damage/hitbox_multipliers)与 `falloff_segments` 逐字段 diff;
3. 对官方 candidateMetrics 的各距离点反解隐含衰减率(官方 E[N] 对距离的斜率 vs 本地 falloff_segments 的分段),判断官方隐含衰减段与本地的差异模式。

- [ ] **Step 3: 形成根因结论(三类)**

- **A 上游内部矛盾**:上游 packs 与 candidateMetrics 同版本自相矛盾(反解忠实但仍对不上)→ 修复方向:overrides + provenance 记录;
- **B 本地反解缺口**:上游 packs 支持(存在某组参数使全部距离点吻合)但本地反解逻辑没推导出来 → 修复方向:修 normalize_weapon/weapon_state 的反解规则;
- **C 版本脱节**:cache/本地 weapons.json 落后于上游当前版本(上游已改 packs 且与 candidateMetrics 一致)→ 修复方向:已被 Task 1 重同步覆盖,直接复验。

输出:根因报告(每把偏差武器一行:weapon_id | 类型 | 失败模式 | diff 结论 | 归类 | 修复建议),写入任务回复与 `.probe/root-cause.md`。

---

### Task 4: 修复与收敛

**Files:**
- 依 Task 3 结论分支:
  - 结论 B → Modify: `src/collectors/game_data_sync.py`(normalize_weapon 反解段)与/或 `src/engine/weapon_state.py`
  - 结论 A → Modify: `data/overrides/manual_corrections.json`(机制已存在,现文件为空列表)
  - 结论 C → 无代码改动,直接复验
- Regenerate: 受影响后重跑 `python -m src.collectors.game_data_sync` 再生成 `data/game/*`

**Interfaces:**
- Consumes: Task 3 根因报告。
- Produces: 全量验证收敛的 `data/game/*`;Task 5 的回归测试以收敛后的数字为准。

- [ ] **Step 1: 按结论实施修复**

- B:改反解逻辑,保持「纯数据驱动、官方锚点注释」风格;改完重跑同步器再生成 weapons.json;
- A:overrides 条目必须含 `reason` 字段引用官方 candidateMetrics 值;同步器已有 applied_overrides 记录链路,确认 provenance.integrity.applied_overrides 非空且含理由;
- C:跳到 Step 2。

- [ ] **Step 2: 复验收敛**

```bash
cd "E:/WK/日常" && "C:/Users/pc/.workbuddy/binaries/python/versions/3.13.12/python.exe" tools/verify_official_reproduction.py --tol 1e-9 --report .probe/repro-fixed.json
```

Expected: 退出码 0(全部 |Δ|≤1e-9)。若有剩余超差点且根因确属上游内部矛盾(结论 A 已 overrides 仍无法归零):核对 overrides 数值;确无法归零的孤点,记录最小残差到 provenance.integrity(新键 `official_reproduction_residual`),并在任务回复说明——不允许静默放过。

- [ ] **Step 3: 原有测试回归**

```bash
cd "E:/WK/日常" && "C:/Users/pc/.workbuddy/binaries/python/envs/default/Scripts/python.exe" -m pytest -x -q
```

Expected: 全 PASS(若 venv 未建:先 `python -m venv C:/Users/pc/.workbuddy/binaries/python/envs/default && <venv python> -m pip install -r requirements.txt`;Task 1 即建)。test_ballistics 的 OFFICIAL 锚点若因数据再生成而失败,核对官方值本身未变——锚点值来自官方输出,不允许为过测改锚点。

- [ ] **Step 4: Commit**

```bash
cd "E:/WK/日常" && git add -A data/game/ data/overrides/ src/ .probe/root-cause.md 2>/dev/null; git commit -m "fix(engine): 官方样本全量复现收敛(P0 修复)"
```

---

### Task 5: 回归测试固化 + CI 接入

**Files:**
- Create: `tests/test_official_reproduction.py`
- Modify: `tests/test_data_integrity.py`(追加哈希回归)
- Modify: `.github/workflows/update.yml`(test job 无需大改,pytest 已跑全测试;确认 python 3.11 兼容新测试)

**Interfaces:**
- Consumes: `tools/verify_official_reproduction.py` 的核心逻辑(测试内联重实现或 import tools 模块均可,取 import 方式:`from tools.verify_official_reproduction import run_verification`——工具需提供可调用入口 `run_verification(tol) -> dict`)。
- Produces: CI test job 即生效的全量逐位回归。

- [ ] **Step 1: 写全量复现回归测试**

```python
"""官方 candidateMetrics 全量复现回归(P0 审计修复固化)。
阈值 1e-9;数据缺失/为空时 skip 并说明(本地无网络不应误报)。
"""
import json, os
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOL = 1e-9

def _samples_path():
    p = os.path.join(ROOT, "data", "game", "validation_samples.json")
    if not os.path.exists(p):
        pytest.skip("validation_samples.json 不存在")
    return p

def test_official_candidate_metrics_reproduced():
    from tools.verify_official_reproduction import run_verification
    result = run_verification(tol=TOL, samples_path=_samples_path())
    assert result["total_points"] > 3000, f"样本点异常稀少:{result['total_points']}"
    worst = result["worst"]
    assert result["fail_count"] == 0, (
        f"{result['fail_count']} 点超差(阈值 {TOL}),最差 {worst['delta']:.4f} @ "
        f"{worst['scenario']}/{worst['candidate']}/{worst['distance']}m"
    )
```

工具端把骨架重构为 `run_verification(tol: float, samples_path: str) -> dict`(返回 total_points/pass_count/fail_count/worst/devisions 摘要),CLI 包装该函数——**保证工具与测试同一实现,不复制逻辑**。

- [ ] **Step 2: 哈希回归(provenance outputs 9 文件)**

在 test_data_integrity.py 追加:按 `game_data_sync._write_json` 同款规范化(`json.dumps(payload, ensure_ascii=False, indent=1)` + 尾部 `\n`)重算 `data/game/*.json` SHA256,与 provenance.json `outputs` 比对:

```python
def test_provenance_output_hashes_match():
    import hashlib
    prov = json.load(open(os.path.join(G, "provenance.json"), encoding="utf-8"))
    for name, expected in prov["outputs"].items():
        payload = json.load(open(os.path.join(G, name), encoding="utf-8"))
        # 口径与 game_data_sync._write_json 严格一致:哈希算 json.dumps(...) 文本本身,
        # 不带尾换行(尾换行仅在写文件时追加)。旧骨架误加 +"\n" 导致 9/9 误报,已更正。
        text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False)
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == expected, f"{name} 哈希不匹配(内容被改动?)"
```

- [ ] **Step 3: 跑全测试 + CI 语法检查**

```bash
cd "E:/WK/日常" && "C:/Users/pc/.workbuddy/binaries/python/envs/default/Scripts/python.exe" -m pytest -q
"C:/Users/pc/.workbuddy/binaries/python/envs/default/Scripts/python.exe" -c "import yaml,sys; yaml.safe_load(open('.github/workflows/update.yml')); print('workflow ok')" || echo "yaml 模块缺失,跳过语法检查(测试已覆盖逻辑)"
```

Expected: pytest 全 PASS(全量复现测试使测试耗时 +2~3 分钟,可接受;超 5 分钟则给该测试加 `@pytest.mark.slow` 并在 CI 中默认跑)。

- [ ] **Step 4: Commit**

```bash
cd "E:/WK/日常" && git add tests/ tools/verify_official_reproduction.py .github/workflows/update.yml
git commit -m "test: 官方样本全量复现回归 + provenance 哈希回归固化(P2)"
```

---

### Task 6: 重算全部榜单

**Files:**
- Regenerate: `data/榜单/*.json`、`docs/榜单/*.md`、`README.md`、`docs/改枪指南.md`(`python -m src.pipeline` 全自动)

**Interfaces:**
- Consumes: Task 4 收敛后的 `data/game/*`;现价表 `data/reference/*.json`。
- Produces: 修正后榜单;Task 7 以重算后榜单数字为准。

- [ ] **Step 1: 后台重算**

```bash
cd "E:/WK/日常" && "C:/Users/pc/.workbuddy/binaries/python/versions/3.13.12/python.exe" -m src.pipeline --beam-width 8
```

束搜索耗时较长(CI 同款参数),用后台运行等待完成;失败则按报错修复后重跑。

- [ ] **Step 2: 对比前后榜单变化**

```bash
cd "E:/WK/日常" && git diff --stat -- README.md docs/榜单/ data/榜单/ | tail -5
```

在 git diff 中抽查:主榜(护甲5弹药5)各距离带 Top5 前后变化,重点核对冲锋枪远距排名是否修正(审计指出远距冲锋枪 E[N] 高估达 54%,修正后应显著后退)。把变化摘要写入任务回复。

- [ ] **Step 3: Commit**

```bash
cd "E:/WK/日常" && git add -A README.md docs/ data/
git commit -m "chore(tierlist): 官方样本收敛后全量重算榜单(远距冲锋枪排序修正)"
```

---

### Task 7: 文档口径统一(P1)

**Files:**
- Modify: `README.md:85-86`(「3774 个样本零偏差」「291 个官方候选零偏差」)、`llms.txt:30-31`、`src/engine/ballistics.py:1-24`(头注释 16 样本表述)、`src/engine/engagement.py:16-17`(同款表述)
- 参照: `docs/audit/2026-09-28-ttk-official-mechanism-audit-report.md`(已提交)

**Interfaces:**
- Consumes: Task 2/4 的最终实测数字(总点数/逐位数/最大 |Δ|;射击间隔 291 取整口径)。
- Produces: 三处口径一致、与实测相符的项目对外声明。

- [ ] **Step 1: 统一改写(以实测数字替换)**

统一模板(数字用 Task 4 复验后的实际值):

- README/llms.txt:`期望击杀发数 E[N]:逐位复现官方 candidateMetrics,<总点数> 个样本点全部 |Δ|≤1e-9(最大 |Δ|<最大值>)`;`射击间隔:291 个官方候选取整后全对(官方仅发布整数 rpm)`;
- ballistics.py 头注释:「16 个样本」段替换为当前验证集规模与收敛结论,并注明验证入口 `tools/verify_official_reproduction.py` 与回归测试;
- engagement.py:16-17 的「3774 样本,99.92% 精确」同步替换;
- 三处口径必须互洽,零偏差表述只允许出现在「取整口径」明确标注处。

- [ ] **Step 2: 口径互洽自检**

```bash
cd "E:/WK/日常" && grep -n "3774\|99.92\|零偏差\|16 个" README.md llms.txt src/engine/ballistics.py src/engine/engagement.py
```

Expected: 无残留旧口径(或仅剩明确标注「取整口径」的合法表述)。

- [ ] **Step 3: Commit**

```bash
cd "E:/WK/日常" && git add README.md llms.txt src/engine/ballistics.py src/engine/engagement.py
git commit -m "docs: 可信度声明统一为全量实测口径(P1 修复)"
```

---

### Task 8: 端到端验收 + 审计报告收尾

**Files:**
- Modify: `docs/audit/2026-09-28-ttk-official-mechanism-audit-report.md`(文末追加「修复结果」附录)

**Interfaces:**
- Consumes: 全部前序任务产物。
- Produces: 验收通过的最终状态。

- [ ] **Step 1: 全套验证**

```bash
cd "E:/WK/日常" && "C:/Users/pc/.workbuddy/binaries/python/envs/default/Scripts/python.exe" -m pytest -q
"C:/Users/pc/.workbuddy/binaries/python/versions/3.13.12/python.exe" tools/verify_official_reproduction.py --tol 1e-9
"C:/Users/pc/.workbuddy/binaries/python/versions/3.13.12/python.exe" -m src.pipeline --render-only && git diff --exit-code -- README.md docs/榜单/ && echo "render 幂等 OK"
```

Expected: pytest 全 PASS;verify 退出码 0 且分级统计达标;--render-only 后榜单文档无 diff(管线与落盘产物一致)。

- [ ] **Step 2: 审计报告追加修复结果附录**

在报告文末追加:修复前后数字对照(基线 vs 收敛)、根因结论(Task 3)、榜单排名变化摘要(Task 6)、验证基础设施现状(Task 5)。

- [ ] **Step 3: 最终提交**

```bash
cd "E:/WK/日常" && git add docs/audit/ && git commit -m "docs(audit): 审计报告追加修复结果附录(验收通过)"
git log --oneline -9
```

---

## Self-Review

1. **Spec coverage**: 审计修复清单 P0(Task 1-4 + 6)、P1(Task 7)、P2(Task 5)全覆盖;设计 spec 的验收标准(Task 8 端到端验收)覆盖。✓
2. **Placeholder scan**: 探查型步骤(Task 1 Step 1、Task 3)均给出明确命令与分支决策树,无 TBD/TODO;实现步骤给出代码骨架与完整行为约束。✓
3. **Type consistency**: `run_verification(tol, samples_path) -> dict` 在 Task 2 定义、Task 5 消费,签名一致;`validation_samples.json` 结构(candidate_metrics: cand_id → [[dist, expected]])在 Task 1/2/5 一致。✓
