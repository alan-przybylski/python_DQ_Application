SELECT
    id,
    email,
    CASE
        WHEN email IS NULL OR email NOT LIKE '%_@_%._%' THEN 1
        ELSE 0
    END AS dq_check
FROM customers;
