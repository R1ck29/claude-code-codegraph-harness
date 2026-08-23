# このハーネスの仕組み

この文書は、Claude Code／Codexを使う業務ユーザーと、社内ZIPを組み立てるIT・AppSec担当向けの説明です。

## まず結論

ローカルコードグラフを作成・検索する完成形のruntimeは構築できています。Claude CodeとCodexの両方が、同じread-only gateway、同じCodebase-Memory、同じindexを使います。Macの公開コードでは外部network拒否下でindexと検索まで実行できました。

ただし、現時点では次の2つを満たしていません。

1. Codexの比較ではgraph条件の入力tokenが48〜52%増え、Claude Codeでgraphを1回強制利用した比較でも有効入力tokenが58〜112%増えた。
2. 社内EDR下のWindows／macOS全対象端末で、子processを含む外部通信・秘密領域遮断の証拠が揃っていない。

したがって、現行 `v0.2.0-rc.1` は「公開コード限定のrelease candidate」です。社内コードへ有効化した完成品、またはtoken削減製品としては承認しません。安全性のため、技術的に動くことと本番採用を分けています。

## 何が動くのか

```text
Claude Code Plugin + Rule ─┐
                            ├─> 社内所有のlocal stdio gateway
Codex user Skill ──────────┘              │
                                          v
                              固定Codebase-Memory native binary
                                          │
                                          v
                           repository別のprivate graph generation

管理者のindex build ──> 検証 ──> 成功時だけcurrentをatomic切替
```

AIから見えるtoolは次の5つだけです。

- `codegraph_status`: 障害診断用の状態確認
- `codegraph_search`: symbol／概念の候補検索
- `codegraph_neighbors`: 直接関係の候補
- `codegraph_impact`: caller／callee方向の影響候補
- `codegraph_architecture`: 件数、言語、entry pointなどの限定概要

index作成、削除、任意Cypher、source本文取得、URL取得、upstream固有toolはAIへ公開しません。通常query自身がcommit、dirty state、backend、gateway、設定hashを毎回確認するため、通常queryの前にstatusを重ねて呼ぶ必要はありません。

## 各部品の役割

| 部品 | 役割 | 公開ZIP | 社内runtime ZIP |
|---|---|---:|---:|
| Claude Code Plugin | 構造質問のroutingとsource再確認手順 | 含む | 含む |
| Claude Code Rule | Plugin外でdata／fallback境界を固定 | 含む | 含む |
| Codex user Skill | global `AGENTS.md`を上書きせず同じroutingを追加 | 含む | 含む |
| `codegraph-gateway` | 5 tool、鮮度、path、出力上限を強制 | 含まない | 4 OS/CPU版を含む |
| Codebase-Memory v0.10.8 | local graph作成・照会 | 含まない | 4 OS/CPU版を含む |
| installer | hash、所有権、OS/CPU選択、rollback | 含む | 含む |
| 評価runner | baseline対graphのtoken／品質／時間比較 | source repository | source repository |

公開GitHub releaseへvendor binaryを置きません。社内pipelineだけが、内部mirrorにある承認済みnative binaryを固定hashで追加します。端末は4組のうち自分のOS／CPUのgatewayとbackendだけをinstallします。

## なぜupstream MCPを直接使わないのか

Graphify `v0.9.48` の固定版には、GitHub通信を行い得るPR toolと外部LLM経路があるため、社内コード用途では不採用です。

Codebase-Memory `v0.10.8` はnative binaryだけを条件付き採用しました。npm、PyPI、Go wrapper、公式installerはGitHubからbinaryをdownloadするため禁止します。また、UI、watcher、auto-index、updaterを無効にします。

それでもupstreamをClaude Code／Codexへ直接登録しません。社内所有gatewayが以下を強制できるためです。

- backend、gateway、設定、GitのSHA-256固定
- absolute pathやsource本文を返さないbounded schema
- repository外state、repository identity別generation
- 失敗buildでcurrentを壊さないatomic切替
- dirty／stale／hash不一致時のfail closed
- release buildへ埋め込んだ公開fixtureのtracked-content fingerprint以外を拒否
- synthetic HOMEとcredential／proxy環境の非継承
- AIからindex更新・mutationを呼べないtool allowlist

## indexの鮮度

管理者が明示的に `gateway index build` を実行します。gatewayはmanaged Gitでtop-level、commit、tracked file manifestを取得し、private generationへindexを作ります。Codebase-Memoryの実statusからnode、edge、skip、partial、not-indexed件数を読み、1件でも不完全ならactiveにしません。

成功したgenerationだけをatomicな `current` pointerへ切り替えます。Claude Code／Codexからの各queryは、現在のcommit、dirty state、backend／gateway／config hashとmanifestを再検証します。不一致ならgraphを使わず、通常のRead、Grep、LSP、testへ戻ります。

## 実際にこのMacで確認したこと

公開repositoryの使い捨てfixture、macOS arm64、Codebase-Memory v0.10.8の固定binaryを使いました。社内コードは使用していません。gateway／backend試験の入力にcredentialは置いていませんが、同一userの秘密領域がOS上不可視だったことまでは証明していません。後述のClaude比較ではclient認証にOAuth／keychainを使用しました。

- 外部networkをdenyし、private Unix-domain socketだけを許可
- 63 tracked files
- 759 nodes、1,760 edges
- parse partial 0、skipped 0、not indexed 0
- `run_bundle_cli` をrepository相対pathと行番号で検索
- impact、architecture、freshnessを取得
- public response JSON Schemaに合格
- 許可root外repositoryを拒否
- 実offline ZIPのinstall→index→MCP query→uninstallに成功

これはWindows runtime、enterprise EDR、他ユーザー領域のfilesystem不可視化、社内コード適格性を証明しません。

## token比較の結果

Codex CLI 0.146.1、`gpt-5.6-sol`、同じ公開fixtureと質問、各条件3回で測定しました。raw回答は保存せず、hash、usage、tool名、oracle件数だけを残しました。

| 質問 | baseline median input | graph median input | 差 | 正答oracle |
|---|---:|---:|---:|---:|
| 1 symbolの定義場所 | 52,037 | 79,176 | +52.15% | 両方3/3 |
| caller、依存先、直接testの追跡 | 134,073 | 198,427 | +48.00% | 両方3/3 |

品質低下は観測しませんでしたが、事前条件の「median input 20%以上削減」には不合格です。この条件ではtool schemaやtool往復のcostが探索削減を上回りました。そのため、常時有効化や「10分の1」の表示は行いません。構造探索を明示的に必要とする場合だけ使うopt-in機能です。

Claude Code 2.1.239、`claude-sonnet-5`、同じ公開fixtureで、baselineと「gatewayを1回呼んでからsourceを確認する」条件も各3回測定しました。

| 質問 | baseline median有効入力 | graph実利用median | 差 | 正答oracle |
|---|---:|---:|---:|---:|
| 1 symbolの定義場所 | 54,464 | 115,250 | +111.61% | 両方3/3 |
| caller、直接test、既定profile | 112,029 | 176,515 | +57.56% | 両方3/3 |

各graph runで `codegraph_search` または `codegraph_impact` が1回実行されました。graphを有効にしただけの別probeではMCPが選択されなかったため、自動tool選択の有効性は確認済みとしません。Claudeの「有効入力」はinput、cache creation、cache readの合計で、Codexのinput fieldとはclientをまたいで比較できません。

この端末はOAuth／keychain認証のため、API key専用の `--bare` ではなく、設定source無効、strict MCP、session非保存、read-only tool限定の通常headless modeを使用しました。OAuth tokenをMCP設定へ書いてはいませんが、gateway processから同一userのsecretをOS上不可視にする試験ではありません。これは公開fixtureの比較証跡であり、社内コードの隔離証跡ではありません。

## offline ZIPの作り方

公開repositoryのprofileはadapterだけを含みます。社内pipelineは次の手順でruntime ZIPを作ります。

1. 公開tag／commit、CI、license、security reviewを確認する。
2. cleanな公開fixtureのtracked-content fingerprintを取得し、その値を
   compile-time allowlistへ固定してgatewayをmacOS／Windows ×
   arm64／x86_64の4種類へbuildする。通常のsource buildは全repositoryを拒否する。
3. Codebase-Memoryの4 native binaryを内部mirrorから取得し、固定archive／executable hashを確認する。
4. 8 binaryと固定license、third-party notices、SBOMをclean staging directoryへ置く。
5. `runtime-matrix.json.in` のgateway version、commit、4 hash、同じfixture
   fingerprintを置換する。
6. builderでZIP、runtime manifest、bundle manifest、`SHA256SUMS`を生成する。
7. secret／malware scan、両OS試験、署名を行う。
8. 実際に試験した同一bytesを社内ポータルへ登録する。

builderはstaging directoryを自動探索せず、profileへ列挙されたregular fileだけを読みます。URL、absolute source、traversal、symlink、重複target、hash不一致を拒否します。

## 利用者PCへのインストール

最初に、ZIPとは別の信頼できる経路で示された署名またはSHA-256を検証します。ZIP内 `SHA256SUMS` は展開後の破損を検出しますが、ZIP全体と一緒に差し替えられた場合の真正性は証明できません。

runtime ZIPではIT担当が、gatewayへcompileされた同一内容の公開fixtureと
そのabsolute rootを指定します。名前や `public-fixture` という文字列だけを
合わせても起動できません。tracked fileの実内容、mode、pathを再計算し、
untracked／ignored fileがあれば拒否します。

```text
./install.sh --dry-run --allowed-root /absolute/approved/public-fixtures
./install.sh --allowed-root /absolute/approved/public-fixtures

powershell.exe -NoProfile -File .\install.ps1 -DryRun -AllowedRoot C:\Approved\PublicFixtures
powershell.exe -NoProfile -File .\install.ps1 -AllowedRoot C:\Approved\PublicFixtures
```

installerは次の順序で動きます。

1. 全checksummed entry、必須file、symlink／reparse pointを確認する。
2. OS／CPUを判定し、対応するgateway／backend pairだけを選ぶ。
3. 明示allowed rootとmanaged Gitのabsolute path／hashを固定する。
4. 未所有Rule、Skill、runtime、MCP registrationとの衝突を確認する。
5. runtime、Rule、Codex Skillをcopyし、local Claude marketplace Pluginを導入する。
6. 同じgateway commandと引数をClaude Code／Codexへ登録する。
7. file／registration hashをreceiptへ記録する。
8. 途中失敗なら、このinstallが作成した変更だけをrollbackする。

GitHub、npm、PyPI、Go registry、vendor serverからdownloadしません。runtime導入には組織管理済みGitが必要です。

uninstallは利用者が変更したfileやregistrationを削除しません。derived graphは誤ったdata lossを避けるため既定で残します。保持禁止policyなら、最初のuninstall時に `--purge-graph-state` または `-PurgeGraphState`を指定します。

## 「外部送信しない」の正確な範囲

| 制御 | 確認できること | それだけでは保証しないこと |
|---|---|---|
| offline installer | download commandを持たない | install後processの通信 |
| local stdio | clientとgatewayがlocal標準入出力を使う | backendや子processのDNS／HTTPS |
| 固定native binary | package wrapper／updaterを使わない | OS・依存・脆弱性を含む完全隔離 |
| synthetic HOME／最小env | 通常のcredential／proxy envを渡さない | 同一user権限で見える全filesystem |
| explicit allowed root + compile-time fixture fingerprint | 許可外root、別内容、untracked／ignored追加をgatewayが拒否 | OS-level network／filesystem隔離、社内コード承認 |
| Mac sandbox試験 | public fixtureで外部network deny下に動作 | Windows／enterprise EDRの証拠 |

社内コード利用には、exact ZIPごとにWindows／macOSの対象CPUで、gateway、backend、Git等の子process全体へDNS／TCP／UDP denyを強制し、HOME、keychain、SSH agent、他repository、credential envを不可視にした証拠が必要です。通常、invalid input、crash、update pathでも確認します。証拠が揃うまでallowed rootを社内repositoryへ向けません。

## 誰が何を担当するか

| 担当 | 責任 |
|---|---|
| 業務ユーザー | 承認済みZIPだけを取得し、指定commandでinstallする |
| 社内配布担当 | 一方向取込、4 runtime build、hash、署名、portal、rollbackを管理する |
| 評価担当 | client／model／task／seedを固定し、baseline対graphを比較する |
| AppSec／endpoint担当 | process-tree egress、filesystem、credential、retentionを両OSで証明する |
| Claude Code／Codex管理者 | managed MCP／Plugin policy、allowed root、既存harnessとの衝突を管理する |

## よくある誤解

- **「localだから外部送信しない」ではありません。** OS／EDRで子processまで遮断します。
- **「Pluginを入れればgraphが動く」ではありません。** 公開ZIPはadapter-onlyです。
- **「graphは正解」ではありません。** sourceとtestが正本です。
- **「tokenが10分の1」ではありません。** Codexは48〜52%、Claudeのgraph実利用は58〜112%増えました。
- **「技術的に動いたので社内展開できる」ではありません。** Windows／enterprise gateが残っています。

## 詳細資料（GitHubへ接続できる評価・管理担当向け）

- [Architecture](https://github.com/R1ck29/claude-code-codegraph-harness/blob/main/docs/architecture.md)
- [Internal integration](https://github.com/R1ck29/claude-code-codegraph-harness/blob/main/docs/internal-integration.md)
- [Threat model](https://github.com/R1ck29/claude-code-codegraph-harness/blob/main/docs/threat-model.md)
- [Codex評価証跡](https://github.com/R1ck29/claude-code-codegraph-harness/blob/main/docs/evidence/codex-v0.2.0-public-token-eval.md)
- [Claude Code評価証跡](https://github.com/R1ck29/claude-code-codegraph-harness/blob/main/docs/evidence/claude-v0.2.0-public-token-eval.md)

このfileが唯一の日本語原本です。bundle builderは同じbytesをZIP直下の `HOW-IT-WORKS-JA.md`へ入れ、testで原本bytes、manifest、`SHA256SUMS`を照合します。
