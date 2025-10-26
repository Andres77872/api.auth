-- ===================================================================================
-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Database Creation Script
-- ===================================================================================
-- This script creates the magic_auth database with proper character set and collation
-- MySQL Database
-- ===================================================================================

-- Create database
CREATE DATABASE IF NOT EXISTS magic_auth 
    DEFAULT CHARACTER SET utf8mb4 
    COLLATE utf8mb4_unicode_ci;

-- Force database collation (fix for MySQL 8/9)
ALTER DATABASE magic_auth 
    CHARACTER SET utf8mb4 
    COLLATE utf8mb4_unicode_ci;

-- Use the database
USE magic_auth;

-- Set proper SQL mode for data integrity
SET sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

-- Set UTF-8 character set
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

SELECT 'Database magic_auth created successfully!' as status;

