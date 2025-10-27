-- ===================================================================================
-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Initial Data Script (Restructured for Group-Based Access)
-- ===================================================================================
-- This script populates initial data required for the authentication system
-- MySQL Database
-- ===================================================================================

USE magic_auth;

-- =================== CREATE ROOT USER ===================
-- Create the first root user (password: admin123)
-- Password hash for 'admin123': 1be6588ad163643cae7ba7bbc6492c9fd035e01f1a1a9ed46e90f8c8ab3494c1
SET @root_user_id = 'usr-550e8400-e29b-41d4-a716-446655440000';
SET @root_user_hash = 'usr-0a0ca5a2-a7c9-11f0-ab33-22316c040a38';
INSERT INTO users (id, user_hash, username, email, password_hash, user_type, created_at, is_active)
VALUES (@root_user_id, @root_user_hash, 'root', 'root@system.local', 
        '1be6588ad163643cae7ba7bbc6492c9fd035e01f1a1a9ed46e90f8c8ab3494c1',
        'root', NOW(), TRUE);

SELECT 'Root user created successfully!' as status, 
       'Username: root, Password: admin123' as credentials;

-- =================== INITIALIZATION COMPLETE ===================
SELECT 'Database initialization complete!' as status,
       'Root user created' as details;

