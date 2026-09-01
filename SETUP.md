# 安装与配置

## 1. 装进 Claude Code

把每个技能目录软链到 `~/.claude/skills/`：

```bash
git clone <repo> && cd <repo>

# 内容集
for d in zmm zmm-mvp zmm-topic zmm-script zmm-hook zmm-flow \
 zmm-resonate zmm-review zmm-title zmm-post zmm-retro; do
 ln -sfn "$PWD/$d" ~/.claude/skills/$d
done

# 商业集
for d in zmm-portfolio zmm-revenue zmm-concentration zmm-dependency zmm-decide; do
 ln -sfn "$PWD/$d" ~/.claude/skills/$d
done

# 两套共用
ln -sfn "$PWD/zmm-track" ~/.claude/skills/zmm-track
```

只想装一套就只跑对应那段。**`zmm-track` 两套都建议装**——没有它，所有「到期再看」的东西都会丢。

## 2. 填配置

```bash
cp config.example.yaml config.yaml
```

**技能只读 `config.yaml`，本体不含任何实例值。** 读不到会明说「配置缺失」并停下，**不会拿示例值假装是你的设定**。

### 只做内容，最少填这些

| 字段 | 为什么必填 |
|---|---|
| `ip.name` / `ip.positioning` / `ip.audience` | 决定所有内容的人称、立场、给谁看 |
| `ip.credibility` | 没有它，「凭什么信你」这类判断无从谈起 |
| `redlines.sell_real` | **不填等于没有红线检查** |
| `redlines.banned_words.hard` | 平台违禁词，按你发的平台填 |
| `voice.do` / `voice.dont` | 改稿时照着清 |
| `platforms` | `domestic_public: true` 的平台走全套红线 |

### 只做生意，最少填这些

| 字段 | 为什么必填 |
|---|---|
| `business.weekly_hours_total` | 组合体检的分母 |
| `business.lines` | 每条至少要 `revenue_monthly` 和 `weekly_hours` |
| `business.privacy.mode` | 要把分析结果发出去就设 `pseudonym` |

**没有产品线数据也能用**——技能会走「问一次」流程，口头给它就行。

### 数据源与凭据

`business.data_sources` 只写「去哪取」，**凭据一律走环境变量或各工具自己的配置，绝不写进本文件**。

## 3. 可选：内容库

`paths.vault_root` 留空 = **无 vault 模式**，技能只做通用判断，并明说哪些依赖真实素材的结论给不了。

想要完整能力（从自己的素材装配、记忆回流、实证规律），指向一个目录并按 `paths` 里的结构放东西。目录不用一次建全，技能会说缺哪个。

## 4. 建议：先填评分锚点

`zmm-review` 的分数标尺**光有定义评不准**。把 `skills/zmm-review/references/评分锚点.md` 里的示例句子换成**你自己成稿里的真实句子**（每档 2 句），然后把 `scoring.anchors_filled` 设为 `true`。

在那之前，评分只给参考区间，不给硬判定。

## 5. 发布前自检

```bash
python3 scripts/leak_scan.py
```

扫作者身份、产品名、金额、账号密钥、本机路径。**发现即退出码 1**，可以挂进发布流程。

---

## 常见问题

**技能说「配置缺失」怎么办？** 检查 `config.yaml` 在仓库根目录、且 YAML 能解析（`python3 -c "import yaml;yaml.safe_load(open('config.yaml'))"`）。

**能只装一两个技能吗？** 能，但内容集的技能之间会互相引用（比如 `zmm-review` 判完会提 `zmm-title`）。缺了的那个它会说「不在当前环境」，不影响主流程。

**为什么红线值不写在技能里？** 因为那是你的，不是这套工具的。**技能负责怎么判，配置负责判什么。**

**为什么很多地方要求「给不出就标未评估」？** 因为「应该没问题」是这套东西明确拒绝接受的答案——它意味着从没认真想过，而写成「风险可控」会让人以为想过了。
