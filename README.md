# Mysql
## Create database
create database EVE

## Create table
create table test( \
&nbsp;&nbsp;&nbsp;&nbsp;ID int primary key, \
&nbsp;&nbsp;&nbsp;&nbsp;name varchar(20), \
&nbsp;&nbsp;&nbsp;&nbsp;max double, \
&nbsp;&nbsp;&nbsp;&nbsp;min double, \
&nbsp;&nbsp;&nbsp;&nbsp;buy_max double, \
&nbsp;&nbsp;&nbsp;&nbsp;buy_min double, \
&nbsp;&nbsp;&nbsp;&nbsp;sell_max double, \
&nbsp;&nbsp;&nbsp;&nbsp;sell_min double, \
&nbsp;&nbsp;&nbsp;&nbsp;update_time time \
) 


Getdate.py 从EVE市场获取Json文件并转换成CSV \
Update2Mysql.py 将CSV文件导入数据库 \
Select.py 根据Json配方来获取原材料 \
app.py 启动Flask 
