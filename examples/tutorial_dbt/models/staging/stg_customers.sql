{{ config(materialized='table') }}

select
    customer_id,
    customer_name,
    region,
    signup_date
from {{ source('raw', 'customers') }}
