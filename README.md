# Eve-cost
Mysql
create database EVE

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