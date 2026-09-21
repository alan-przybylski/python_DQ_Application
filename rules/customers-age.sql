SELECT
    id,
    age,
    CASE
        WHEN age IS NULL OR age NOT BETWEEN 18 AND 120 THEN 1
        ELSE 0
    END AS dq_check
FROM customers;
