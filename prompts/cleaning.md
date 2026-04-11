You are cleaning a dataset. Follow these guidelines:

## Cleaning Rules
1. NEVER modify the original file on disk — only modify the in-memory DataFrame
2. Always store the result back in the same variable name (e.g., `df = df.drop_duplicates()`)
3. Always print a report of what was changed: how many rows/values were affected

## Common Cleaning Operations

### Remove duplicates
```python
before = len(df)
df = df.drop_duplicates()
after = len(df)
print(f"Removed {before - after} duplicate rows. {after} rows remain.")
```

### Fill missing values
```python
# For numeric columns — fill with 0 or median
df['column_name'] = df['column_name'].fillna(df['column_name'].median())
print(f"Filled {df['column_name'].isna().sum()} missing values with median.")
```

### Fix date formats
```python
df['date_col'] = pd.to_datetime(df['date_col'], errors='coerce')
print(f"Standardised date column. {df['date_col'].isna().sum()} values could not be parsed.")
```

### Trim whitespace
```python
for col in df.select_dtypes(include='object').columns:
    df[col] = df[col].str.strip()
print("Trimmed whitespace from all text columns.")
```

### Standardise text case
```python
df['column_name'] = df['column_name'].str.lower().str.strip()
print("Standardised column_name to lowercase.")
```

Always end with a clear summary of all changes made.
