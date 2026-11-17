-- ============================================================
-- Real-Time Disaster Prediction System — Database Setup
-- Run this script inside MySQL Workbench
-- ============================================================
--
-- How to run in MySQL Workbench:
--   1. File → Open SQL Script… → select this file
--   2. Change the password on the CREATE USER line below
--   3. Click the yellow lightning-bolt icon (Execute)
--   4. Check the Output panel for green checkmarks
--
-- ============================================================

CREATE DATABASE IF NOT EXISTS disaster_prediction_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- Change 'change_me_strong_password' to a real password, then put
-- the SAME password in your project's .env as DB_PASSWORD=
CREATE USER IF NOT EXISTS 'disaster_user'@'localhost'
  IDENTIFIED BY 'change_me_strong_password';

GRANT ALL PRIVILEGES ON disaster_prediction_db.* TO 'disaster_user'@'localhost';
FLUSH PRIVILEGES;

-- Verification (results appear in Workbench Result Grid)
SHOW DATABASES LIKE 'disaster_prediction_db';
SELECT User, Host FROM mysql.user WHERE User = 'disaster_user';
