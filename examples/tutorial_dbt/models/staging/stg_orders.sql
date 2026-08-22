{{ config(materialized='table') }}

select
    order_id,
    order_date,
    customer_id,
    product_id,
    quantity,
    revenue,
    region
from {{ source('raw', 'orders') }}
