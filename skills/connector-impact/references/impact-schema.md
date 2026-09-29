# Impact schema

Shape of Impact's data: objects, fields, filters, traps. For TL meaning, see
`impact-to-tl-mapping.md`. Source: Impact Brand API v14 and MCP docs at `integrations.impact.com`.

## Access routes

The user brings one route. This skill never holds a login.

| Route | Setup | Best for |
|---|---|---|
| Impact MCP | Custom connector `https://mcp.impact.com/mcp`, signed in with the user's Impact login | Most questions; aggregates on Impact's side |
| Impact Brand API | `AccountSID` + a token the user creates (Settings → Technical → API) | Action-level detail, long ranges |
| CSV export | Reports: Performance by Partner, Performance by Day, Advanced Action Listing | No setup |

MCP tools on a Brand account:

| Tool | Returns | Use |
|---|---|---|
| `query_performance` | Clicks, actions, revenue, grouped by partner or date | Per-partner, per-day numbers |
| `list_partners` | Program partners | Join input |
| `investigate_order_action` | The action for one order id | One disputed conversion |
| `list_action_inquiries`, `get_action_inquiry` | Open credit claims | Missing credit (some editions only) |

Map each tool's first response to the objects below before doing any math.

## Action (one conversion)

`GET /Advertisers/{AccountSID}/Actions`; items per order: `.../Actions/{ActionId}/Items`.

Filters: `ActionDateStart` / `ActionDateEnd` (on `EventDate`; use these for windows),
`LockingDateStart` / `LockingDateEnd`, `CampaignId`, `State`.

| Field | Type | Meaning |
|---|---|---|
| `Id` | string | Action id |
| `CampaignId`, `CampaignName` | integer, string | Program |
| `ActionTrackerId`, `ActionTrackerName`, `EventCode` | integer, string, string | Event type |
| `MediaPartnerId`, `MediaPartnerName` | integer, string | Credited partner |
| `State` | string | `PENDING`, `APPROVED`, `REVERSED` |
| `AdId` | integer | Ad or link behind the winning click |
| `Amount`, `DeltaAmount`, `IntendedAmount` | number | Sale value: current, last change, original |
| `Payout`, `DeltaPayout`, `IntendedPayout` | number | Partner commission: current, last change, original |
| `ClientCost` | number | Payout plus fees |
| `Currency` | string | ISO 4217, for all money on the row |
| `EventDate`, `ReferringDate`, `CreationDate`, `LockingDate`, `ClearedDate` | date-time | See mapping 1.2 |
| `ReferringType`, `ReferringDomain` | string | Attribution method, click site |
| `PromoCode` | string | Checkout code |
| `SharedId` | string | Value passed on the winning click's link |
| `Oid` | string | Brand's order id |
| `CustomerId`, `CustomerStatus` | string | Non-PII id; `NEW` / `EXISTING` if configured |
| `CustomerCountry`, `CustomerRegion`, `CustomerCity` | string | If passed |
| `Note` | string | Free text |

`ActionUpdate` records each change: `ActionId`, `State`, `StateDetail`, `DeltaPayout`,
`DeltaAmount`, `ContractId`, `UpdateDate`.

## Click

One click: `GET /Advertisers/{AccountSID}/Campaigns/{CampaignId}/Clicks/{ClickId}`. Bulk:
`GET /Advertisers/{AccountSID}/Programs/{ProgramId}/ClickExport`, one day per call (`Date`),
filters `MediaId`, `AdId`, `UniqueClick`, dates after 9 April 2024 only.

| Field | Type | Meaning |
|---|---|---|
| `Id` | string | Journey id (`im_ref`) |
| `CampaignId`, `CampaignName` | integer, string | Program |
| `EventDate` | date-time | Click time |
| `MediaId`, `MediaName` | integer, string | Partner (same value as `MediaPartnerId`) |
| `AdId`, `AdName`, `AdType` | integer, string, string | `AdType` includes `VIDEO`, `ONLINE_TRACKING_LINK`, `COUPON` |
| `ReferringUrl`, `ReferringDomain`, `LandingPageUrl` | string | Source and landing page |
| `SharedId` | string | Value passed on the link |
| `PartnerRelated.SubId1`, `.SubId2`, `.SubId3` | string | Partner-set link tags |
| `UniqueClick` | boolean | IAB-unique |
| `DeviceType`, `Os`, `Browser`, `CustomerCountry` | string | Context |
| `Payout` | number | Pay per click, if any |

## Partner

`GET /Advertisers/{AccountSID}/MediaPartners` (filters `CampaignId`, `Id`, `RelationshipState`
`ACTIVE` / `INACTIVE`, `GroupId`, `Country`) and `.../MediaPartners/{PartnerId}`.

| Field | Type | Meaning |
|---|---|---|
| `Id` | integer | Same as `MediaPartnerId` / `MediaId` |
| `Name`, `Description` | string | Often a person's or agency's name |
| `Website` | string | Partner's site |
| `Properties[]` | array | `Name`, `Type`, `Platform`, `Url`; a YouTube `Url` is join key 2 |
| `Programs[]` | array | `ContractId`, `ContractName`, `JoinDate`, `ExpirationDate` |
| `PartnerValues.Value1-3` | string | Brand-set custom values |
| `Currency`, `Country`, `Timezone` | string | Payout currency, location |
| `PartnerType` | string | Direct or marketplace |
| `DateCreated`, `DateLastUpdated` | date-time | Record dates |
| `Contacts[]` | array | Personal data. Never copy into output |

## Reports

`GET /Advertisers/{AccountSID}/ReportExport/{ReportId}` with `StartDate`, `EndDate`. Columns come
from the report's `MetaDataUri`; read it before trusting a column name.

| Report (Brand account / Partner account) | Grain | Notes |
|---|---|---|
| Performance by Partner / Performance by Brand | One row per partner (or brand) | Grouped numbers |
| Performance by Day | One row per day | Grouped numbers |
| Advanced Action Listing | One row per action | The only report with each action's status |

Grouped report columns (checked on a Partner account, September 2026):

| Column | Meaning |
|---|---|
| `Clicks` | Unique clicks |
| `Actions` | Approved plus pending, reversals excluded. No status split |
| `Sales`, `Leads`, `Calls`, `Mobile_Installs` | Actions split by type |
| `Sale_Amount` | Sale value ("Revenue" on the Brand dashboard) |
| `Action_Cost` | Commission on actions |
| `Other_Cost` | Fixed payments made through Impact (e.g. a flat fee), which can be spread as equal daily amounts across the payment period |
| `Total_Cost` | Includes `Action_Cost`, bonuses and `Other_Cost` |
| `CR`, `EPC`, `AOV`, `RR` | Conversion rate, earnings per click, average order value, reversal rate |

On a Partner account the labels say "Earnings" instead of "Cost" (Action Earnings, Total
Earnings); the underlying columns are the same. Reports have a display-currency setting, so
figures can arrive already converted by Impact.

Advanced Action Listing columns include `Action_Id`, `oid`, `Status`, `status_detail`,
`Event_Type`, `Referral_Date`, `Action_Date`, `Locking_Date`, `Actual_Clearing_Date`,
`Sale_Amount`, `Payout`, `Original_Payout`, `Bonus_Payout`, `Promo_Code`, `SubId1` to `SubId3`,
`SharedId`, `Ad`, `Referring_URL`, `Customer_Id`, `original_currency` and
`original_currency_sale_amount`.

## Traps

- In the API, SubIds are on the Click (`PartnerRelated`) and Actions carry `SharedId`. The
  Advanced Action Listing shows `SubId1` to `SubId3` and `SharedId` on each action.
- The Click's partner fields are `MediaId` / `MediaName`, not `MediaPartnerId`.
- On Actions, `StartDate` / `EndDate` filter on last-updated, not conversion date.
- Impact has no video views.
- `/Mediapartners/` paths fail on a Brand account, and `/Advertisers/` paths on a Partner account.
- Grouped reports count pending actions inside `Actions`; pending actions can reverse until their
  `LockingDate`.
- A flat fee paid through Impact shows as daily `Other_Cost` amounts with zero actions. Sum it over
  the payment period; one day's amount is not the fee.
