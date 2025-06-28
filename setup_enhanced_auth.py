#!/usr/bin/env python3
"""
Setup script for Enhanced Multi-Project Authentication System

This script initializes the enhanced authentication database from scratch.
Use this for new installations or when you want to start fresh.

Usage:
    python setup_enhanced_auth.py
    python setup_enhanced_auth.py --with-sample-data
"""

import os
import sys
import argparse
import logging
from datetime import datetime

import pymysql

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "192.168.1.90"),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_MYSQL_PASSWORD"),
    "charset": "utf8mb4"
}

ENHANCED_DB_NAME = "magic_auth_enhanced"


def create_database():
    """Create the enhanced authentication database"""
    logger.info("Creating enhanced authentication database...")
    
    with pymysql.connect(**DB_CONFIG) as con:
        cur = con.cursor()
        
        # Create database if it doesn't exist
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {ENHANCED_DB_NAME}")
        cur.execute(f"USE {ENHANCED_DB_NAME}")
        
        # Create tables
        tables = get_table_definitions()
        
        for table_name, table_sql in tables.items():
            logger.info(f"Creating table: {table_name}")
            cur.execute(table_sql)
        
        con.commit()
        logger.info("✓ Database schema created successfully")


def get_table_definitions():
    """Get the SQL definitions for all tables"""
    return {
        "users": """
            CREATE TABLE IF NOT EXISTS users (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Global user identifier',
                username VARCHAR(255) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE,
                password_hash VARCHAR(64) NOT NULL COMMENT 'SHA256 hash of password',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                
                INDEX idx_user_hash (user_hash),
                INDEX idx_username (username),
                INDEX idx_email (email)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Global user accounts'
        """,
        
        "projects": """
            CREATE TABLE IF NOT EXISTS projects (
                id INT PRIMARY KEY AUTO_INCREMENT,
                project_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Project identifier',
                project_name VARCHAR(255) NOT NULL,
                project_description TEXT,
                project_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                
                INDEX idx_project_hash (project_hash),
                INDEX idx_project_name (project_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Project/Application registry'
        """,
        
        "user_projects": """
            CREATE TABLE IF NOT EXISTS user_projects (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT NOT NULL,
                project_id INT NOT NULL,
                user_project_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Unique identifier for this user-project relationship',
                granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                granted_by INT COMMENT 'User ID who granted access',
                revoked_at TIMESTAMP NULL,
                revoked_by INT COMMENT 'User ID who revoked access',
                is_active BOOLEAN DEFAULT TRUE,
                
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (granted_by) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (revoked_by) REFERENCES users(id) ON DELETE SET NULL,
                
                UNIQUE KEY unique_user_project (user_id, project_id),
                INDEX idx_user_id (user_id),
                INDEX idx_project_id (project_id),
                INDEX idx_user_project_hash (user_project_hash)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User access to projects'
        """,
        
        "user_groups": """
            CREATE TABLE IF NOT EXISTS user_groups (
                id INT PRIMARY KEY AUTO_INCREMENT,
                project_id INT NOT NULL,
                group_name VARCHAR(255) NOT NULL,
                group_description TEXT,
                permissions JSON COMMENT 'Array of permission strings',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                
                UNIQUE KEY unique_group_per_project (project_id, group_name),
                INDEX idx_project_id (project_id),
                INDEX idx_group_name (group_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Groups within projects'
        """,
        
        "user_project_groups": """
            CREATE TABLE IF NOT EXISTS user_project_groups (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_project_id INT NOT NULL,
                group_id INT NOT NULL,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                assigned_by INT COMMENT 'User ID who made the assignment',
                removed_at TIMESTAMP NULL,
                removed_by INT COMMENT 'User ID who removed the assignment',
                is_active BOOLEAN DEFAULT TRUE,
                
                FOREIGN KEY (user_project_id) REFERENCES user_projects(id) ON DELETE CASCADE,
                FOREIGN KEY (group_id) REFERENCES user_groups(id) ON DELETE CASCADE,
                FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (removed_by) REFERENCES users(id) ON DELETE SET NULL,
                
                UNIQUE KEY unique_user_group (user_project_id, group_id),
                INDEX idx_user_project_id (user_project_id),
                INDEX idx_group_id (group_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User membership in project groups'
        """,
        
        "user_sessions": """
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_project_id INT NOT NULL,
                session_token VARCHAR(64) UNIQUE NOT NULL,
                session_key VARCHAR(255) COMMENT 'Legacy compatibility',
                session_value TEXT COMMENT 'Legacy compatibility',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                ip_address VARCHAR(45),
                user_agent TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                
                FOREIGN KEY (user_project_id) REFERENCES user_projects(id) ON DELETE CASCADE,
                
                INDEX idx_session_token (session_token),
                INDEX idx_user_project_id (user_project_id),
                INDEX idx_expires_at (expires_at),
                INDEX idx_last_activity (last_activity)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User session tracking'
        """
    }


def create_default_groups(project_id, cursor):
    """Create default groups for a project"""
    default_groups = [
        ("admin", "Project administrators", '["admin", "read", "write", "delete", "manage_users", "manage_groups"]'),
        ("user", "Regular users", '["read", "write"]'),
        ("readonly", "Read-only users", '["read"]')
    ]
    
    for group_name, description, permissions in default_groups:
        cursor.execute("""
            INSERT INTO user_groups (project_id, group_name, group_description, permissions, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, [project_id, group_name, description, permissions])


def create_sample_data():
    """Create sample projects and users for testing"""
    logger.info("Creating sample data...")
    
    config = DB_CONFIG.copy()
    config['database'] = ENHANCED_DB_NAME
    
    with pymysql.connect(**config) as con:
        cur = con.cursor()
        
        # Create sample projects
        import secrets
        
        projects = [
            ("Main Application", "Primary application project"),
            ("Admin Panel", "Administrative interface"),
            ("API Gateway", "API management and routing")
        ]
        
        project_ids = []
        project_hashes = []
        
        for project_name, project_description in projects:
            project_hash = secrets.token_hex(32).upper()
            project_hashes.append(project_hash)
            
            cur.execute("""
                INSERT INTO projects (project_hash, project_name, project_description, project_created)
                VALUES (%s, %s, %s, NOW())
            """, [project_hash, project_name, project_description])
            
            project_id = con.insert_id()
            project_ids.append(project_id)
            
            # Create default groups for this project
            create_default_groups(project_id, cur)
            
            logger.info(f"✓ Created project: {project_name} (hash: {project_hash})")
        
        # Create sample users
        import hashlib
        
        users = [
            ("admin", "admin@example.com", "admin123"),
            ("john_doe", "john@example.com", "password123"),
            ("jane_smith", "jane@example.com", "password456")
        ]
        
        user_ids = []
        
        for username, email, password in users:
            password_hash = hashlib.sha256(password.encode()).hexdigest().upper()
            user_hash = secrets.token_hex(32).upper()
            
            cur.execute("""
                INSERT INTO users (user_hash, username, email, password_hash, created_at)
                VALUES (%s, %s, %s, %s, NOW())
            """, [user_hash, username, email, password_hash])
            
            user_id = con.insert_id()
            user_ids.append(user_id)
            
            logger.info(f"✓ Created user: {username} (password: {password})")
        
        # Grant access and assign roles
        
        # Admin user gets access to all projects as admin
        admin_user_id = user_ids[0]
        for i, project_id in enumerate(project_ids):
            user_project_hash = secrets.token_hex(32).upper()
            
            cur.execute("""
                INSERT INTO user_projects (user_id, project_id, user_project_hash, granted_at)
                VALUES (%s, %s, %s, NOW())
            """, [admin_user_id, project_id, user_project_hash])
            
            user_project_id = con.insert_id()
            
            # Assign to admin group
            cur.execute("""
                SELECT id FROM user_groups 
                WHERE project_id = %s AND group_name = 'admin' AND is_active = 1
            """, [project_id])
            
            admin_group = cur.fetchone()
            if admin_group:
                cur.execute("""
                    INSERT INTO user_project_groups (user_project_id, group_id, assigned_at)
                    VALUES (%s, %s, NOW())
                """, [user_project_id, admin_group[0]])
            
            logger.info(f"✓ Granted admin access to project: {project_hashes[i]}")
        
        # Regular users get access to first project only
        for user_id in user_ids[1:]:
            user_project_hash = secrets.token_hex(32).upper()
            
            cur.execute("""
                INSERT INTO user_projects (user_id, project_id, user_project_hash, granted_at, granted_by)
                VALUES (%s, %s, %s, NOW(), %s)
            """, [user_id, project_ids[0], user_project_hash, admin_user_id])
            
            user_project_id = con.insert_id()
            
            # Assign to user group
            cur.execute("""
                SELECT id FROM user_groups 
                WHERE project_id = %s AND group_name = 'user' AND is_active = 1
            """, [project_ids[0]])
            
            user_group = cur.fetchone()
            if user_group:
                cur.execute("""
                    INSERT INTO user_project_groups (user_project_id, group_id, assigned_at, assigned_by)
                    VALUES (%s, %s, NOW(), %s)
                """, [user_project_id, user_group[0], admin_user_id])
        
        con.commit()
        
        # Display sample login information
        logger.info("\n" + "="*60)
        logger.info("SAMPLE LOGIN INFORMATION")
        logger.info("="*60)
        logger.info("Admin User:")
        logger.info(f"  Username: admin")
        logger.info(f"  Password: admin123")
        logger.info(f"  Projects: All projects (admin access)")
        logger.info("")
        logger.info("Regular Users:")
        logger.info(f"  Username: john_doe, Password: password123")
        logger.info(f"  Username: jane_smith, Password: password456")
        logger.info(f"  Projects: {project_hashes[0]} (user access)")
        logger.info("")
        logger.info("Project Hashes:")
        for i, (name, _) in enumerate(projects):
            logger.info(f"  {name}: {project_hashes[i]}")
        logger.info("="*60)


def test_database_connection():
    """Test database connection"""
    logger.info("Testing database connection...")
    
    try:
        with pymysql.connect(**DB_CONFIG) as con:
            cur = con.cursor()
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            logger.info(f"✓ Connected to MySQL {version}")
            return True
    except Exception as e:
        logger.error(f"✗ Database connection failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Setup Enhanced Multi-Project Authentication System')
    parser.add_argument('--with-sample-data', action='store_true',
                        help='Create sample projects and users for testing')
    parser.add_argument('--force', action='store_true',
                        help='Force recreation of database (drops existing)')
    
    args = parser.parse_args()
    
    logger.info("Enhanced Multi-Project Authentication Setup")
    logger.info("=" * 50)
    
    # Test database connection
    if not test_database_connection():
        logger.error("Setup aborted due to connection failure")
        sys.exit(1)
    
    # Check if database exists
    if args.force:
        logger.info("Force mode: Dropping existing database...")
        with pymysql.connect(**DB_CONFIG) as con:
            cur = con.cursor()
            cur.execute(f"DROP DATABASE IF EXISTS {ENHANCED_DB_NAME}")
            logger.info("✓ Existing database dropped")
    
    try:
        # Create database and tables
        create_database()
        
        # Create sample data if requested
        if args.with_sample_data:
            create_sample_data()
        
        logger.info("\n🎉 Setup completed successfully!")
        logger.info("Your enhanced authentication system is ready to use.")
        logger.info("\nNext steps:")
        logger.info("1. Update your .env file with the database configuration")
        logger.info("2. Start your FastAPI application")
        logger.info("3. Visit /docs to see the API documentation")
        logger.info("4. Use /user/login endpoint to authenticate")
        
        if args.with_sample_data:
            logger.info("\nSample data has been created. Check the login information above.")
    
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main() 