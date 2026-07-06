from services.stock_name_service import (
    get_stock_name,
    find_stock_by_name,
    get_stock_id_by_name,
)

print("3481 =", get_stock_name("3481"))
print("2330 =", get_stock_name("2330"))
print("0050 =", get_stock_name("0050"))

print("搜尋 台積 =", find_stock_by_name("台積")[:5])
print("搜尋 群創 =", find_stock_by_name("群創")[:5])
print("群創代號 =", get_stock_id_by_name("群創"))