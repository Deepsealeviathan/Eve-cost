# Eve-cost
Mysql
## Create database
create database EVE

## Create table
create table test(
	ID int primary key,
	name varchar(20),
    max double,
    min double,
    buy_max double,
    buy_min double,
    sell_max double,
    sell_min double,
    update_time time
)

Getdate.py 从EVE市场获取Json文件并转换成CSV
Update2Mysql.py 将CSV文件导入数据库
Select.py 根据Json配方来获取原材料
app.py 启动Flask