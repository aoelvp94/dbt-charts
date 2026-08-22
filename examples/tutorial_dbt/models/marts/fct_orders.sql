{{ config(materialized='table') }}

select
    o.order_id,
    o.order_date,
    o.customer_id,
    o.product_id,
    o.quantity,
    o.revenue,
    o.region,
    c.customer_name,
    c.signup_date as customer_signup_date,
    p.product_name,
    p.category as product_category,
    p.price as product_price,
    o.quantity * p.price as calculated_revenue
from {{ ref('stg_orders') }} o
left join {{ ref('stg_customers') }} c on o.customer_id = c.customer_id
left join {{ ref('stg_products') }} p on o.product_id = p.product_id
