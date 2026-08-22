{{ config(materialized='table') }}

select
    product_id,
    product_name,
    category,
    price
from {{ source('raw', 'products') }}
