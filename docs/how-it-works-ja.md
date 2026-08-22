# このハーネスの仕組み

この文書は、Claude Codeを利用する業務ユーザー、社内配布担当、評価担当が「何を配り、何が端末に入り、どこまで安全性を担保する仕組みか」を短時間で理解するための説明です。

## まず結論

このハーネスには、次の2つの役割があります。

1. コードグラフ製品を導入する前に、公開コードだけを使って既存方式と比較する。
2. 採用が承認された機能を、GitHubへ接続できない端末にも社内ZIPで安全に配る。

公開repositoryの評価版には、Claude Codeの使い方を制御するPluginとRule、比較runner、ZIP作成機能、macOS／Windows用installerがあります。このうち、業務ユーザー向けoffline ZIPへ入るのはPlugin、Rule、installerと説明・検証用ファイルです。Graphify、Codebase-Memory、コードグラフMCP server、その他のvendor binaryは入りません。

したがって、現在のZIPをインストールしただけでコードグラフ検索が有効になったり、トークン量や回答品質が改善したりするわけではありません。

## 全体は「評価」と「配布」の2本立て

```text
【評価の流れ】

公開fixture ──> 同じ質問・条件で比較 ──> 品質／時間／利用量を記録 ──> 採否を判断
                    │
                    ├─ baseline（現在の方式）
                    ├─ Graphify
                    ├─ Codebase-Memory
                    └─ Pluginと組み合わせたhybrid

【配布の流れ】

公開tag／release ──> 社内組立・審査 ──> 検証済み社内ZIP ──> 社内ポータル ──> 利用者PC
                           │
                           └─ 承認済みの社内Ruleやartifactだけを追加
```

評価と配布を分ける理由は、性能が良いことと、社内コードを安全に扱えることが別の問題だからです。品質比較に勝っても、外部通信、ライセンス、更新、Windows／macOS対応、ロールバックの証拠が揃わなければ本番ZIPには追加しません。

## 各部品の役割

| 部品 | 役割 | 現在の評価版に含まれるか |
| --- | --- | --- |
| `codegraph-evaluator` Plugin | 構造的な質問を承認済みグラフへ振り分け、重要な結論をソースとテストで再確認する手順をClaude Codeへ与える | 含まれる |
| `source-verifier` Agent | `Read`、`Grep`、`Glob`だけで、グラフ由来の主張を読み取り専用で検証する | 含まれる |
| `codegraph-harness.md` Rule | グラフを正解ではなく索引として扱い、外部PR、URL、更新、cloud LLMなどへ使わないルールを追加する | Pluginとは別に含まれる |
| 評価runner | 公開fixture上で複数条件を同じ手順で実行し、成功、時間、利用量、costなどを比較可能なJSONへまとめる | source repositoryに含まれる |
| bundle builder | 公開資材と、社内で明示承認されたファイルだけから再現可能なZIPを作る | source repositoryに含まれる |
| macOS／Windows installer | 展開済みZIPを検証し、ローカルmarketplaceからPluginとRuleを導入する | 含まれる |
| コードグラフbackend／MCP | 実際にコードグラフを作成・検索するengine | 含まれない。未選定 |

Pluginはengineそのものではありません。「承認済みのグラフMCPがそのsessionに存在する場合の使い方」を定義します。MCPがなければ、通常のRead、Grep、Glob、LSP、テストへ戻ります。

## 比較検証はどう動くか

評価担当は、公開fixture、質問セット、比較条件、反復回数、seedを決めます。runnerは `tasks × conditions × repetitions` を記録したseedで並べ替え、各条件をshellを介さないprocessとして実行します。

既定ではraw stdout／stderrを保存せず、promptやrepository pathはhashで記録します。raw出力を保存する場合は明示指定が必要で、出力先を評価対象repositoryやハーネス内に置くことは拒否されます。

現行releaseは `company-source` を、質問セットやcondition設定を読む前、processを起動する前に無条件で拒否します。設定JSONや証跡IDで解除することはできません。つまり、この公開runnerで社内コードを評価する経路は現在存在しません。

比較結果から直ちに製品を採用するのではなく、次の順番で判断します。

1. upstreamを変更せず安全に使えるか。
2. 固定commandの薄いwrapperで安全境界を作れるか。
3. 最小forkを保守する必要があるか。
4. 条件を満たさなければ採用しない。

## 社内ZIPはどう作るか

公開repositoryは、社内コード、private Rule、社内path、認証情報、評価結果、生成グラフを保持しません。

社内組立pipelineは、次の順序で一方向に資材を取り込みます。

1. 公開tag、commit、CI結果を確認する。
2. 社内環境でテストを再実行する。
3. 承認済みartifactがある場合だけ、内部mirrorから用意する。
4. private profileへ、追加する各ファイルのsource、ZIP内target、SHA-256を明示する。
5. builderでZIPを作り、secret scan、malware scan、OS別install試験を行う。
6. ZIPを署名するか、ZIPとは別の信頼できる経路でSHA-256を配布する。
7. 実際に試験した同一bytesのZIPを社内ポータルへ登録する。

builderはvendor directoryを自動走査しません。profileへ列挙され、指定SHA-256と一致したregular fileだけを追加します。公開profileへvendor fileを指定するとbuildは失敗します。

## 利用者PCへのインストール

利用者はGitHub、Git、PyPI、npm、vendor release serverへ接続する必要がありません。

最初に、社内ポータルが別経路で示すSHA-256または署名を使い、ZIP全体を展開前に検証します。ZIP内の `SHA256SUMS` は展開後ファイルの破損や部分的な差し替えを検出しますが、ZIP全体と一緒に置き換えられた場合の真正性は証明できません。

installerは次の順序で動きます。

1. 必須ファイルと `SHA256SUMS` の全hashを確認する。
2. `--dry-run` または `-DryRun` では、変更せず導入予定先だけを表示する。
3. 既存Ruleがこのextensionの所有物か、導入後に利用者が変更していないかをreceiptとhashで確認する。
4. ZIP内のlocal marketplaceをversion別directoryへcopyする。
5. RuleをClaude CodeのRules directoryへcopyする。
6. local pathを指定してClaude Code Pluginをuser scopeへ登録する。
7. version、導入先、Rule hash、backupなどをreceiptへ記録する。

未所有の同名Ruleや利用者が変更したRuleへは上書きせず停止します。途中で失敗した場合は、追加途中のPlugin、marketplace、Ruleを元の状態へ戻します。アンインストールもreceiptに記録した範囲だけを対象にし、導入後に利用者が変更したRuleは削除せず残します。

## Claude Code利用時に起きること

PluginとRuleは、Claude Codeへ次の行動方針を与えます。

1. callers、callees、依存経路、architecture境界、変更影響候補などの構造質問だけを、承認済みグラフMCPへ問い合わせる。
2. グラフのbackend、version、index対象revision、鮮度が確認できなければ通常のソース探索へ戻る。
3. グラフ結果を静的解析由来の索引として扱う。
4. 重要な結論は、read-only Agentまたは通常toolsで現在のsourceとtestsを確認する。

静的グラフだけでは、reflection、runtime dependency injection、macro、生成コード、環境変数による分岐を確定できません。そのため、グラフ結果を根拠に直接コードを変更する設計にはしていません。

## 「外部送信しない」の範囲

| 対象 | 現時点で確認できること | この仕組みだけでは保証しないこと |
| --- | --- | --- |
| 公開bundle | 社内データとvendor backendを含まない | 社内pipelineが後から追加するprivate資材の安全性 |
| bundle builder | 外部からdownloadせず、明示されたlocal fileだけを読む | build環境そのもののnetwork isolation |
| endpoint installer | GitHub、package registry、vendor serverからdownloadする処理を持たず、local marketplaceを使う | Claude Code本体や将来backendのruntime通信 |
| 評価runner | Python runner自身はnetwork clientを持たず、現行版ではcompany sourceを拒否する | 起動したClaude Codeや候補processの通信をOSで遮断すること |
| local `stdio` MCP | Claude Codeとbackend間の通信方式がlocal process入出力である | backend processが別途DNSやHTTPSを使わないこと |

「localで動く」「stdioを使う」「offline ZIPで配る」という説明だけでは、backendの外向き通信がない証明になりません。本番追加前に、OS、container／VM、firewall、EDRなどでbackendと子processのDNS、HTTP(S)、proxy、update、telemetryを拒否し、その動的証拠をversionごとに取得する必要があります。

Claude Code本体が利用する承認済みservice経路も、組織の契約と管理policyで別途確定する必要があります。

## 現在の候補判定

| 候補 | 社内コード用途の現在判定 | 確認済み事項と未確認事項 |
| --- | --- | --- |
| Graphify `v0.9.48` 固定commit | 不採用 | GitHubへ接続できるPR toolsと外部LLM経路をsourceで確認済み。現在の固定版をそのまま社内コードへ使わない |
| Codebase-Memory `v0.10.8` 固定commit | 未採用・条件付き候補 | package manager wrapperとonline installerはGitHubからdownloadするため禁止。native binaryの動的zero-egress、OS別動作、子process遮断は未確認 |

この判定は「GraphifyまたはCodebase-Memoryを公開fixtureで比較すること」と、「社内コードへ使うこと」を分けています。公開fixtureでの性能評価が可能でも、社内コード適格性を意味しません。

## 誰が何を担当するか

| 担当 | 主な責任 |
| --- | --- |
| 業務ユーザー | 社内ポータルから承認済みZIPを取得し、組織指定の方法で検証、dry-run、installする |
| 社内配布担当 | 公開tagを一方向に取り込み、社内資材を外へ戻さず、署名、OS試験、portal公開、rollbackを管理する |
| 評価担当 | 公開fixtureで比較条件を揃え、品質、時間、利用量、失敗を記録する |
| AppSec／endpoint担当 | exact binary、子process、DNSを含むzero-egressと保存先・権限を動的に検証する |
| Claude Code管理者 | Plugin、Rules、managed MCP、permission、既存ハーネスとの境界を中央管理する |

## よくある誤解

- **「ZIPだから安全」ではありません。** 展開前にZIP外のSHA-256または署名を確認します。
- **「Pluginを入れればグラフが使える」わけではありません。** 現在のPluginにはbackendやMCP serverがありません。
- **「installerが通信しないから全体も通信しない」とは限りません。** Claude Codeと将来backendの通信制御は別に必要です。
- **「グラフ結果が正解」ではありません。** 重要な判断はsourceとtestsで再確認します。
- **「トークンが10分の1になる」保証はありません。** 記事や提供元の数値は、この組織のrepositoryと運用条件における実測値ではありません。

## 詳細資料（GitHubへ接続できる評価・管理担当向け）

- [Architecture](https://github.com/R1ck29/claude-code-codegraph-harness/blob/main/docs/architecture.md)
- [Evaluation protocol](https://github.com/R1ck29/claude-code-codegraph-harness/blob/main/docs/evaluation-protocol.md)
- [Offline distribution](https://github.com/R1ck29/claude-code-codegraph-harness/blob/main/docs/offline-distribution.md)
- [Internal harness integration](https://github.com/R1ck29/claude-code-codegraph-harness/blob/main/docs/internal-integration.md)
- [Threat model](https://github.com/R1ck29/claude-code-codegraph-harness/blob/main/docs/threat-model.md)
- [Candidate egress audit](https://github.com/R1ck29/claude-code-codegraph-harness/blob/main/docs/candidate-egress-audit.md)

GitHubへアクセスできない利用者は、この文書だけでインストール前の判断に必要な概要を確認できます。詳細資料や社内固有の手順が必要な場合は、社内配布担当が承認済み文書を同じポータルから提供します。

## この文書の管理方法

説明を複数ファイルへコピーすると内容がずれるため、`docs/how-it-works-ja.md`を唯一の原本にしています。bundle builderは同じbytesをoffline ZIP直下の`HOW-IT-WORKS-JA.md`へ配置します。repositoryの`README.md`とZIPの`README-INSTALL.txt`は内容を複製せず、この原本への入口だけを示します。

テストでは、原本の存在、2つの入口、ZIP内のファイル名とbytes一致、manifest、`SHA256SUMS`への収録を確認します。このため、GitHubを読める評価・管理担当と、GitHubへ接続できない業務ユーザーが同じ説明を読み、更新時の差分も1か所で管理できます。
