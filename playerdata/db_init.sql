CREATE USER api WITH LOGIN;
CREATE DATABASE playerdata WITH OWNER api;
GRANT ALL PRIVILEGES ON  DATABASE playerdata TO api;