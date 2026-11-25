-- ============================================================
-- ERP Analytics Lab · MySQL 8 建库脚本
-- 由 app/db/models.py 自动导出，请勿手工修改后不回写模型
-- 生成命令：python scripts/export_schema.py
-- ============================================================
CREATE TABLE dim_date (
	date_id INTEGER NOT NULL AUTO_INCREMENT, 
	full_date DATE NOT NULL, 
	year INTEGER NOT NULL, 
	quarter INTEGER NOT NULL, 
	month INTEGER NOT NULL, 
	month_name VARCHAR(16) NOT NULL, 
	`year_month` VARCHAR(7) NOT NULL, 
	year_quarter VARCHAR(6) NOT NULL, 
	week_of_year INTEGER NOT NULL, 
	day_of_week INTEGER NOT NULL, 
	is_weekend BOOL NOT NULL, 
	PRIMARY KEY (date_id)
);

CREATE TABLE dim_employee (
	employee_id INTEGER NOT NULL AUTO_INCREMENT, 
	employee_name VARCHAR(32) NOT NULL, 
	team VARCHAR(32) NOT NULL, 
	`role` VARCHAR(32) NOT NULL, 
	region VARCHAR(16) NOT NULL, 
	hire_date DATE NOT NULL, 
	is_active BOOL NOT NULL, 
	PRIMARY KEY (employee_id)
);

CREATE TABLE dim_supplier (
	supplier_id INTEGER NOT NULL AUTO_INCREMENT, 
	supplier_name VARCHAR(64) NOT NULL, 
	region VARCHAR(16) NOT NULL, 
	lead_time_days INTEGER NOT NULL, 
	rating FLOAT NOT NULL, 
	PRIMARY KEY (supplier_id)
);

CREATE TABLE dim_customer (
	customer_id INTEGER NOT NULL AUTO_INCREMENT, 
	customer_name VARCHAR(96) NOT NULL, 
	industry VARCHAR(32) NOT NULL, 
	region VARCHAR(16) NOT NULL, 
	city VARCHAR(32) NOT NULL, 
	tier VARCHAR(4) NOT NULL, 
	channel VARCHAR(16) NOT NULL, 
	acquisition_source VARCHAR(16) NOT NULL, 
	contract_date DATE NOT NULL, 
	customer_manager_id INTEGER NOT NULL, 
	annual_contract_value FLOAT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	PRIMARY KEY (customer_id), 
	FOREIGN KEY(customer_manager_id) REFERENCES dim_employee (employee_id)
);

CREATE TABLE dim_product (
	product_id INTEGER NOT NULL AUTO_INCREMENT, 
	sku VARCHAR(32) NOT NULL, 
	product_name VARCHAR(96) NOT NULL, 
	category VARCHAR(32) NOT NULL, 
	brand VARCHAR(32) NOT NULL, 
	unit VARCHAR(8) NOT NULL, 
	unit_cost FLOAT NOT NULL, 
	list_price FLOAT NOT NULL, 
	supplier_id INTEGER NOT NULL, 
	launch_date DATE NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	PRIMARY KEY (product_id), 
	UNIQUE (sku), 
	FOREIGN KEY(supplier_id) REFERENCES dim_supplier (supplier_id)
);

CREATE TABLE fact_ai_usage (
	usage_id INTEGER NOT NULL AUTO_INCREMENT, 
	date_id INTEGER NOT NULL, 
	employee_id INTEGER NOT NULL, 
	scenario VARCHAR(32) NOT NULL, 
	query_count INTEGER NOT NULL, 
	accepted_count INTEGER NOT NULL, 
	minutes_saved FLOAT NOT NULL, 
	PRIMARY KEY (usage_id), 
	FOREIGN KEY(date_id) REFERENCES dim_date (date_id), 
	FOREIGN KEY(employee_id) REFERENCES dim_employee (employee_id)
);
CREATE INDEX ix_fau_date ON fact_ai_usage (date_id);

CREATE TABLE fact_marketing_spend (
	spend_id INTEGER NOT NULL AUTO_INCREMENT, 
	date_id INTEGER NOT NULL, 
	channel VARCHAR(24) NOT NULL, 
	campaign_name VARCHAR(48) NOT NULL, 
	cost_amount FLOAT NOT NULL, 
	leads_count INTEGER NOT NULL, 
	revenue_attributed FLOAT NOT NULL, 
	PRIMARY KEY (spend_id), 
	FOREIGN KEY(date_id) REFERENCES dim_date (date_id)
);

CREATE TABLE sys_user (
	user_id INTEGER NOT NULL AUTO_INCREMENT, 
	username VARCHAR(32) NOT NULL, 
	password_hash VARCHAR(160) NOT NULL, 
	full_name VARCHAR(32) NOT NULL, 
	`role` VARCHAR(24) NOT NULL, 
	employee_id INTEGER, 
	is_active BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (user_id), 
	UNIQUE (username), 
	FOREIGN KEY(employee_id) REFERENCES dim_employee (employee_id)
);

CREATE TABLE fact_customer_ticket (
	ticket_id INTEGER NOT NULL AUTO_INCREMENT, 
	customer_id INTEGER NOT NULL, 
	created_date_id INTEGER NOT NULL, 
	topic_type VARCHAR(24) NOT NULL, 
	channel VARCHAR(16) NOT NULL, 
	ai_handled INTEGER NOT NULL, 
	first_response_minutes INTEGER NOT NULL, 
	resolution_hours FLOAT NOT NULL, 
	satisfaction INTEGER NOT NULL, 
	converted_to_opportunity INTEGER NOT NULL, 
	PRIMARY KEY (ticket_id), 
	FOREIGN KEY(customer_id) REFERENCES dim_customer (customer_id), 
	FOREIGN KEY(created_date_id) REFERENCES dim_date (date_id)
);
CREATE INDEX ix_fct_created ON fact_customer_ticket (created_date_id);

CREATE TABLE fact_inventory_snapshot (
	snapshot_id INTEGER NOT NULL AUTO_INCREMENT, 
	date_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	warehouse VARCHAR(16) NOT NULL, 
	on_hand_qty INTEGER NOT NULL, 
	safety_stock INTEGER NOT NULL, 
	in_transit_qty INTEGER NOT NULL, 
	unit_cost FLOAT NOT NULL, 
	inventory_value FLOAT NOT NULL, 
	PRIMARY KEY (snapshot_id), 
	FOREIGN KEY(date_id) REFERENCES dim_date (date_id), 
	FOREIGN KEY(product_id) REFERENCES dim_product (product_id)
);
CREATE INDEX ix_fis_date_product ON fact_inventory_snapshot (date_id, product_id);

CREATE TABLE fact_inventory_transaction (
	txn_id INTEGER NOT NULL AUTO_INCREMENT, 
	date_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	warehouse VARCHAR(16) NOT NULL, 
	txn_type VARCHAR(16) NOT NULL, 
	qty INTEGER NOT NULL, 
	ref_no VARCHAR(32) NOT NULL, 
	unit_cost FLOAT NOT NULL, 
	PRIMARY KEY (txn_id), 
	FOREIGN KEY(date_id) REFERENCES dim_date (date_id), 
	FOREIGN KEY(product_id) REFERENCES dim_product (product_id)
);
CREATE INDEX ix_fit_date ON fact_inventory_transaction (date_id);
CREATE INDEX ix_fit_product ON fact_inventory_transaction (product_id);

CREATE TABLE fact_lead_opportunity (
	lead_id INTEGER NOT NULL AUTO_INCREMENT, 
	lead_name VARCHAR(96) NOT NULL, 
	customer_id INTEGER, 
	source_channel VARCHAR(16) NOT NULL, 
	created_date_id INTEGER NOT NULL, 
	close_date_id INTEGER, 
	owner_employee_id INTEGER NOT NULL, 
	stage VARCHAR(16) NOT NULL, 
	expected_amount FLOAT NOT NULL, 
	actual_amount FLOAT NOT NULL, 
	win_probability FLOAT NOT NULL, 
	ai_assisted INTEGER NOT NULL, 
	cycle_days INTEGER NOT NULL, 
	loss_reason VARCHAR(64), 
	PRIMARY KEY (lead_id), 
	FOREIGN KEY(customer_id) REFERENCES dim_customer (customer_id), 
	FOREIGN KEY(created_date_id) REFERENCES dim_date (date_id), 
	FOREIGN KEY(close_date_id) REFERENCES dim_date (date_id), 
	FOREIGN KEY(owner_employee_id) REFERENCES dim_employee (employee_id)
);
CREATE INDEX ix_flo_created ON fact_lead_opportunity (created_date_id);
CREATE INDEX ix_flo_stage ON fact_lead_opportunity (stage);

CREATE TABLE fact_purchase_order (
	purchase_id INTEGER NOT NULL AUTO_INCREMENT, 
	purchase_no VARCHAR(32) NOT NULL, 
	supplier_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	order_date_id INTEGER NOT NULL, 
	arrival_date_id INTEGER NOT NULL, 
	qty INTEGER NOT NULL, 
	total_amount FLOAT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	PRIMARY KEY (purchase_id), 
	UNIQUE (purchase_no), 
	FOREIGN KEY(supplier_id) REFERENCES dim_supplier (supplier_id), 
	FOREIGN KEY(product_id) REFERENCES dim_product (product_id), 
	FOREIGN KEY(order_date_id) REFERENCES dim_date (date_id), 
	FOREIGN KEY(arrival_date_id) REFERENCES dim_date (date_id)
);

CREATE TABLE fact_sales_order (
	order_id INTEGER NOT NULL AUTO_INCREMENT, 
	order_no VARCHAR(32) NOT NULL, 
	customer_id INTEGER NOT NULL, 
	employee_id INTEGER NOT NULL, 
	order_date_id INTEGER NOT NULL, 
	delivery_date_id INTEGER NOT NULL, 
	channel VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	payment_status VARCHAR(16) NOT NULL, 
	gross_amount FLOAT NOT NULL, 
	discount_amount FLOAT NOT NULL, 
	net_amount FLOAT NOT NULL, 
	cost_amount FLOAT NOT NULL, 
	gross_profit FLOAT NOT NULL, 
	delivery_days INTEGER NOT NULL, 
	is_return BOOL NOT NULL, 
	PRIMARY KEY (order_id), 
	UNIQUE (order_no), 
	FOREIGN KEY(customer_id) REFERENCES dim_customer (customer_id), 
	FOREIGN KEY(employee_id) REFERENCES dim_employee (employee_id), 
	FOREIGN KEY(order_date_id) REFERENCES dim_date (date_id), 
	FOREIGN KEY(delivery_date_id) REFERENCES dim_date (date_id)
);
CREATE INDEX ix_fso_customer ON fact_sales_order (customer_id);
CREATE INDEX ix_fso_date ON fact_sales_order (order_date_id);
CREATE INDEX ix_fso_employee ON fact_sales_order (employee_id);

CREATE TABLE sys_refresh_token (
	jti VARCHAR(64) NOT NULL, 
	user_id INTEGER NOT NULL, 
	expires_at DATETIME NOT NULL, 
	revoked INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (jti), 
	FOREIGN KEY(user_id) REFERENCES sys_user (user_id)
);

CREATE TABLE fact_sales_order_item (
	order_item_id INTEGER NOT NULL AUTO_INCREMENT, 
	order_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	qty INTEGER NOT NULL, 
	unit_price FLOAT NOT NULL, 
	discount_rate FLOAT NOT NULL, 
	revenue_amount FLOAT NOT NULL, 
	cost_amount FLOAT NOT NULL, 
	PRIMARY KEY (order_item_id), 
	FOREIGN KEY(order_id) REFERENCES fact_sales_order (order_id), 
	FOREIGN KEY(product_id) REFERENCES dim_product (product_id)
);
CREATE INDEX ix_fsoi_order ON fact_sales_order_item (order_id);
CREATE INDEX ix_fsoi_product ON fact_sales_order_item (product_id);
