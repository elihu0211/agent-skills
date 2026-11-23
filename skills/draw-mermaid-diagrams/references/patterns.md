# Mermaid 現代圖表範本與語意邊框參考

本檔收錄符合深／淺色原生主題切換的各類 Mermaid 範本。所有範本均不使用寫死的背景填色或字色，僅於 `subgraph` 採透明底（`fill:transparent`）搭配語意色邊框。

## 目錄

- [建議語意邊框色票](#建議語意邊框色票)
- [分層系統架構圖（flowchart LR）](#分層系統架構圖flowchart-lr)
- [端對端時序圖（sequenceDiagram）](#端對端時序圖sequencediagram)
- [實體關聯圖（erDiagram）](#實體關聯圖erdiagram)
- [狀態機圖（stateDiagram-v2）](#狀態機圖statediagram-v2)
- [品牌靜態雙圖切換（HTML picture）](#品牌靜態雙圖切換html-picture)

## 建議語意邊框色票

以下中等明度語意色在深色（`#18181B`）與淺色（`#FFFFFF`）畫布上皆具足夠對比，僅用於 `stroke` 邊框：

| 語意層級 | 色碼 | 適用場景 |
| --- | --- | --- |
| 琥珀（Amber） | `#D97706` | 外部來源、閘道、邊緣設備、警告 |
| 藍（Blue） | `#2563EB` | API 介面、接入層、核心關聯儲存 |
| 紫（Violet） | `#7C3AED` | 語意引擎、推論核心、領域邏輯 |
| 綠（Emerald） | `#059669` | 協同服務、知識輸出、通過狀態 |
| 灰（Slate） | `#64748B` | 保留原庫、延伸未實作項目（搭 `stroke-dasharray: 5 5`） |

## 分層系統架構圖（flowchart LR）

```mermaid
---
config:
  look: neo
  flowchart:
    curve: basis
    nodeSpacing: 28
    rankSpacing: 46
---
flowchart LR
    subgraph Sources["來源層"]
        direction TB
        App["企業系統（REST）"]
        Edge["邊緣閘道（MQTT）"]
    end

    subgraph Ingress["接入層"]
        direction TB
        API["API 服務（FastAPI）"]
        DB[("狀態與佇列（PostgreSQL）")]
        API <-->|"落盤"| DB
    end

    subgraph Core["核心層"]
        direction TB
        Worker["背景處理引擎"]
        Future["延伸模組（規劃中）"]
        Worker -.->|"後續延伸"| Future
    end

    App -->|"JSON"| API
    Edge -->|"正規化 JSON"| API
    DB -->|"非同步消費"| Worker

    style Sources fill:transparent,stroke:#D97706,stroke-width:1.5px
    style Ingress fill:transparent,stroke:#2563EB,stroke-width:1.5px
    style Core fill:transparent,stroke:#059669,stroke-width:1.5px
    style Future stroke-dasharray: 5 5
```

## 端對端時序圖（sequenceDiagram）

```mermaid
---
config:
  look: neo
---
sequenceDiagram
    autonumber
    participant Client as 來源端
    participant API as 接入服務
    participant Store as 資料庫

    Client->>API: 送出請求
    API->>Store: 驗證並落盤

    alt 驗證通過
        Store-->>API: 寫入成功
        API-->>Client: 回傳 200 OK
    else 驗證失敗
        API-->>Client: 回傳違規明細
    end
```

## 實體關聯圖（erDiagram）

```mermaid
---
config:
  look: neo
---
erDiagram
    identities ||--o{ events : "關聯事件"

    identities {
        text shared_id PK "共享代號"
        text display_name "顯示名稱"
    }

    events {
        uuid event_id PK "事件編號"
        text shared_id FK "對應共享代號"
        timestamptz received_at "接收時間"
    }
```

## 狀態機圖（stateDiagram-v2）

```mermaid
---
config:
  look: neo
---
stateDiagram-v2
    [*] --> Pending: 接收事件
    Pending --> Persisted: 檢核通過
    Pending --> Blocked: 檢核失敗
    Persisted --> [*]
    Blocked --> [*]
```

## 品牌靜態雙圖切換（HTML picture）

若圖表需要固定品牌色票而非跟隨主題，於 GitHub Markdown 使用標準 `<picture>` 搭配 `prefers-color-scheme`：

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/architecture-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/architecture-light.svg">
  <img alt="系統架構圖" src="assets/architecture-light.svg">
</picture>
```
