# Power BI semantic model for retail performance

This portfolio case study designs a Power BI report for market leads who need to answer three questions. How much did we sell? How does that compare with the same point in the last fiscal year? Which markets can each viewer see? The design uses synthetic retail sell-through and includes a small fixture for checking the measures by hand.

## Model and data contract

The model imports the curated output from the [retail pipeline](pipeline-design.md). Each `fact_sales_daily` row represents one sale date, market code, and SKU. SQLite stores net sales as integer pence. Export the exact decimal GBP amount as `net_sales_gbp` and import it into Power BI as Fixed decimal number. Import `units` as Whole number.

| Table | Key or grain | Purpose |
| --- | --- | --- |
| `fact_sales_daily` | `sale_date, market_code, sku` | Daily units and net sales by market and SKU |
| `Date` | `date` | Complete daily fiscal calendar with `fiscal_year`, `fiscal_week`, `fiscal_period`, and `fiscal_day_number` |
| `Market` | `market_code` | Market names and the dimension where the access filter is applied |
| `Product` | `sku` | Product names and categories |
| `Refresh Control` | One row | `certified_from_date` and `certified_through_date` for the continuous interval approved for reporting |
| `Market Access` | `upn, market_code` | The market codes assigned to each viewer, with UPNs stored lowercase and trimmed |

Create single-direction, active one-to-many relationships from `Date`, `Market`, and `Product` to the fact table on their keys. Keep both control tables disconnected. For a local prototype, import a CSV export of the Gold fact, maintain an explicit fiscal calendar and a one-row control file, and derive the market and SKU keys from the fact. In a shared deployment, source dimensions and access assignments from maintained reference tables. Reconcile to the published batch before advancing the certified dates. Sales activity alone cannot establish that every expected feed arrived.

The fiscal calendar specifies a Sunday start and a 4-4-5 period pattern. For a 53-week year, place the additional week in period 12. Store fiscal year as an integer and restart the fiscal day number at 1 each year. Validate that the Date table has one row per day and covers the full fiscal years used in the comparison. Comparing by fiscal day aligns the weekdays within the current and prior years.

## Measures and date behaviour

| Measure | Definition |
| --- | --- |
| Net Sales (GBP) | Sum of daily net sales |
| Units | Sum of daily units |
| Average Net Price (GBP) | Total net sales divided by total units in the current filter context |
| Fiscal YTD Net Sales (GBP) | Net sales from fiscal day 1 through the latest certified date visible in the current date context |
| Prior Fiscal YTD Net Sales (GBP) | Net sales over the same number of fiscal days in the preceding year |
| Fiscal YTD YoY % | Current fiscal YTD minus prior fiscal YTD, divided by the positive prior total |

The average net price weights each group by its units. The fiscal measures use the selected date context to choose an end date, then include every fiscal day through that date. On a trend chart each point shows a running value within its fiscal year. At the total level the measure uses the latest certified date in scope. Dates after the certified interval return blank when they are the only dates in scope. [Microsoft Learn describes how KEEPFILTERS intersects the date filters.](https://learn.microsoft.com/en-us/dax/keepfilters-function-dax)

Enter the following measures separately.

```dax
Net Sales (GBP) = SUM ( fact_sales_daily[net_sales_gbp] )

Units = SUM ( fact_sales_daily[units] )

Average Net Price (GBP) = DIVIDE ( [Net Sales (GBP)], [Units] )

Fiscal Reporting Date =
VAR CertifiedFrom = SELECTEDVALUE ( 'Refresh Control'[certified_from_date] )
VAR CertifiedThrough = SELECTEDVALUE ( 'Refresh Control'[certified_through_date] )
RETURN
    IF (
        NOT ISBLANK ( CertifiedFrom ) && NOT ISBLANK ( CertifiedThrough ),
        CALCULATE (
            MAX ( 'Date'[date] ),
            KEEPFILTERS ( 'Date'[date] >= CertifiedFrom ),
            KEEPFILTERS ( 'Date'[date] <= CertifiedThrough )
        )
    )
```

```dax
Fiscal YTD Net Sales (GBP) =
VAR ReportingDate = [Fiscal Reporting Date]
VAR CertifiedFrom = SELECTEDVALUE ( 'Refresh Control'[certified_from_date] )
VAR FiscalYear =
    CALCULATE (
        SELECTEDVALUE ( 'Date'[fiscal_year] ),
        REMOVEFILTERS ( 'Date' ),
        'Date'[date] = ReportingDate
    )
VAR FiscalStart =
    CALCULATE (
        MIN ( 'Date'[date] ),
        REMOVEFILTERS ( 'Date' ),
        'Date'[fiscal_year] = FiscalYear,
        'Date'[fiscal_day_number] = 1
    )
RETURN
    IF (
        NOT ISBLANK ( ReportingDate )
            && NOT ISBLANK ( FiscalStart )
            && FiscalStart >= CertifiedFrom,
        CALCULATE (
            [Net Sales (GBP)],
            REMOVEFILTERS ( 'Date' ),
            'Date'[fiscal_year] = FiscalYear,
            'Date'[date] <= ReportingDate
        )
    )
```

```dax
Prior Fiscal YTD Net Sales (GBP) =
VAR ReportingDate = [Fiscal Reporting Date]
VAR CertifiedFrom = SELECTEDVALUE ( 'Refresh Control'[certified_from_date] )
VAR FiscalYear =
    CALCULATE (
        SELECTEDVALUE ( 'Date'[fiscal_year] ),
        REMOVEFILTERS ( 'Date' ),
        'Date'[date] = ReportingDate
    )
VAR FiscalDay =
    CALCULATE (
        SELECTEDVALUE ( 'Date'[fiscal_day_number] ),
        REMOVEFILTERS ( 'Date' ),
        'Date'[date] = ReportingDate
    )
VAR PriorWindow =
    FILTER (
        ALL ( 'Date' ),
        'Date'[fiscal_year] = FiscalYear - 1
            && 'Date'[fiscal_day_number] <= FiscalDay
    )
RETURN
    IF (
        NOT ISBLANK ( ReportingDate )
            && COUNTROWS ( PriorWindow ) = FiscalDay
            && MINX ( PriorWindow, 'Date'[date] ) >= CertifiedFrom,
        CALCULATE ( [Net Sales (GBP)], REMOVEFILTERS ( 'Date' ), PriorWindow )
    )
```

```dax
Fiscal YTD YoY % =
VAR CurrentSales = [Fiscal YTD Net Sales (GBP)]
VAR PriorSales = [Prior Fiscal YTD Net Sales (GBP)]
RETURN
    IF (
        NOT ISBLANK ( CurrentSales ) && PriorSales > 0,
        DIVIDE ( CurrentSales - PriorSales, PriorSales )
    )
```

The comparison resets the Date filters and retains the market and product context. If the prior year has 52 weeks and the current comparison ends in week 53, the prior and percentage measures show blank. Use the three base measures on a report page scoped to the certified interval.

## Market-level access

Create one dynamic RLS role and apply these two table filters. The first limits the access map to the viewer's own assignments. The second limits the Market dimension to matching assignments and passes the filter to the sales fact through its active relationship.

`Market Access` table filter

```dax
'Market Access'[upn] = LOWER ( USERPRINCIPALNAME () )
```

`Market` table filter

```dax
VAR ViewerUPN = LOWER ( USERPRINCIPALNAME () )
VAR MarketCode = 'Market'[market_code]
RETURN
    COUNTROWS (
        FILTER (
            'Market Access',
            'Market Access'[upn] = ViewerUPN
                && 'Market Access'[market_code] = MarketCode
        )
    ) > 0
```

This is an Import model example. Map consumers to the dynamic role and test with actual Viewer accounts in the service. Workspace Admins, Members, and Contributors have edit access and are outside this RLS boundary. Limit access to the upstream database separately and treat RLS as a row-control mechanism. [Microsoft Learn documents workspace roles and RLS testing.](https://learn.microsoft.com/power-bi/service-admin-rls)

## Independent validation fixture

This hand-check fixture covers two fiscal years. The SQLite demo covers 13–14 February 2026, so use the fixture for the year-over-year tests. Set `certified_from_date` to 2025-02-02 and `certified_through_date` to 2026-02-14. The fictional feeds are complete across that interval and unlisted days have zero activity. Set the FY2025 start to 2025-02-02 and the FY2026 start to 2026-02-01. The last row deliberately exercises the cutoff.

| sale_date | market_code | sku | units | net_sales_gbp |
| --- | --- | --- | ---: | ---: |
| 2025-02-02 | NORTH | SKU-A | 2 | 40.00 |
| 2025-02-15 | NORTH | SKU-A | 2 | 40.00 |
| 2025-02-16 | NORTH | SKU-A | 5 | 99.00 |
| 2026-02-01 | NORTH | SKU-A | 3 | 70.00 |
| 2026-02-14 | NORTH | SKU-A | 2 | 50.00 |
| 2026-02-14 | SOUTH | SKU-A | 4 | 100.00 |
| 2026-02-15 | NORTH | SKU-A | 1 | 30.00 |

| Test | Expected result |
| --- | --- |
| NORTH, days 1–14 of FY2026 | £120 current fiscal YTD, £80 prior fiscal YTD, +50.0% YoY, 5 units, £24.00 average net price |
| NORTH, visual filtered to 14 Feb only | Current fiscal YTD remains £120. The day-level Net Sales measure shows £50. |
| NORTH, visual filtered to 15 Feb only | Fiscal comparison measures are blank |
| SOUTH, days 1–14 of FY2026 | £100 current fiscal YTD. YoY is blank because there is no prior sales amount. |
| Both markets in scope, days 1–14 of FY2026 | £220 current fiscal YTD and £80 prior fiscal YTD |
| Viewer with only NORTH | Sees NORTH in a market slicer and £120 fiscal YTD across all accessible sales |
| Viewer with NORTH and SOUTH | Sees both slicer values and £220 fiscal YTD across all accessible sales |
| Viewer in the role with no market assignment | Sees an empty market slicer and blank sales measures |
| Prior fiscal start is before the certified history | Prior fiscal YTD and YoY are blank |

Reconcile net sales and units against the Gold output at the total, market, and SKU levels. For the SQLite demo after the correction, the two-day slice should reconcile to 350 units and £560.00 in LON, and 245 units and £395.00 in MAN. Verify the partial selection and cutoff tests, then exercise the access cases on the detail and total views. Save the expected and observed values, Viewer identity, and dataset refresh ID with the acceptance record. Use the [delivery playbook](delivery-playbook.md) for UAT, approval, and handover. These are example checks for a future Power BI implementation.
