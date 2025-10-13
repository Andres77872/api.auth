-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Database Creation Script
-- MySQL Database
CREATE SCHEMA IF NOT EXISTS magic_auth;
-- Create database
CREATE DATABASE IF NOT EXISTS magic_auth DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE magic_auth;

-- Force database collation (fix for MySQL 8/9)
ALTER DATABASE magic_auth CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Set proper SQL mode
SET sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'; 