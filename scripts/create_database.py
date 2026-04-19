#!/usr/bin/env python3
"""
Database Creation Script for Magic Auth System

This script creates the database from scratch by executing all SQL files in order:
1. Tables (database, tables, indexes, constraints, initial data, views)
2. Stored Procedures (all procedure files in order)

Usage:
    python scripts/create_database.py
    
Environment Variables (optional):
    DB_HOST - Database host (default: localhost)
    DB_PORT - Database port (default: 3306)
    DB_USER - Database user (default: root)
    DB_MYSQL_PASSWORD - Database password (default: prompt)
"""

import os
import sys
import getpass
import pymysql
from pathlib import Path


# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_MYSQL_PASSWORD', None),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'autocommit': False
}

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = BASE_DIR / 'schemas'

# Files to execute in order
TABLE_FILES = [
    'tables/01_create_database.sql',
    'tables/02_create_tables.sql',
    'tables/03_create_indexes.sql',
    'tables/04_add_constraints.sql',
    'tables/05_initialize_data.sql',
    'tables/06_create_views.sql',
    'tables/07_error_logs.sql',
    'tables/08_activity_logging_tables.sql',
]

STORED_PROCEDURE_FILES = [
    'stored_procedures/01_user_management.sql',
    'stored_procedures/02_user_groups.sql',
    'stored_procedures/03_projects.sql',
    'stored_procedures/04_project_groups.sql',
    'stored_procedures/05_global_roles.sql',
    'stored_procedures/06_permission_assignments.sql',
    'stored_procedures/07_sessions_analytics.sql',
    'stored_procedures/08_admin_operations.sql',
    'stored_procedures/09_system_maintenance.sql',
    'stored_procedures/10_error_logging.sql',
    'stored_procedures/11_activity_logging.sql',
    'stored_procedures/12_activity_context.sql',
    'stored_procedures/13_api_keys.sql',
]

TRIGGER_FILES = [
    'triggers/01_activity_logging_triggers.sql',
    'triggers/02_permission_activity_triggers.sql',
    'triggers/03_api_key_activity_triggers.sql',
]


def print_header(text):
    """Print a formatted header"""
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80)


def print_step(step_num, total_steps, text):
    """Print a formatted step"""
    print(f"\n[{step_num}/{total_steps}] {text}")


def execute_sql_file(connection, file_path):
    """
    Execute a SQL file with proper handling of delimiters and multiple statements
    
    Args:
        connection: PyMySQL connection object
        file_path: Path to SQL file
    """
    print(f"    Executing: {file_path.name}...", end=" ")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # Split by delimiter changes and execute
        cursor = connection.cursor()
        current_delimiter = ';'
        statements = []
        current_statement = []
        
        for line in sql_content.split('\n'):
            line_stripped = line.strip()
            
            # Check for delimiter change
            if line_stripped.upper().startswith('DELIMITER'):
                if current_statement:
                    stmt = '\n'.join(current_statement).strip()
                    if stmt and not stmt.startswith('--'):
                        statements.append((stmt, current_delimiter))
                    current_statement = []
                
                # Extract new delimiter
                parts = line_stripped.split()
                if len(parts) > 1:
                    current_delimiter = parts[1]
                continue
            
            # Skip empty lines and comments
            if not line_stripped or line_stripped.startswith('--'):
                continue
            
            current_statement.append(line)
            
            # Check if statement ends with current delimiter
            if line_stripped.endswith(current_delimiter):
                stmt = '\n'.join(current_statement).strip()
                # Remove the delimiter from the end
                if current_delimiter != ';':
                    stmt = stmt[:-len(current_delimiter)].strip()
                else:
                    stmt = stmt[:-1].strip()
                
                if stmt and not stmt.startswith('--'):
                    statements.append((stmt, current_delimiter))
                current_statement = []
        
        # Add any remaining statement
        if current_statement:
            stmt = '\n'.join(current_statement).strip()
            if stmt and not stmt.startswith('--'):
                statements.append((stmt, current_delimiter))
        
        # Execute all statements
        for stmt, delim in statements:
            if stmt:
                try:
                    cursor.execute(stmt)
                except Exception as e:
                    # Ignore "database exists" and "table exists" errors
                    if 'already exists' not in str(e).lower():
                        raise
        
        connection.commit()
        cursor.close()
        print("✓ Done")
        return True
        
    except Exception as e:
        print(f"✗ Failed")
        print(f"    Error: {str(e)}")
        connection.rollback()
        return False


def create_database():
    """Main function to create the database"""
    print_header("Magic Auth Database Creation Script")
    
    # Get password if not provided
    if not DB_CONFIG['password']:
        DB_CONFIG['password'] = getpass.getpass(f"Enter password for {DB_CONFIG['user']}@{DB_CONFIG['host']}: ")
    
    print(f"\nConnecting to MySQL at {DB_CONFIG['host']}:{DB_CONFIG['port']}...")
    
    try:
        # Connect without specifying database
        connection = pymysql.connect(**DB_CONFIG)
        print("✓ Connected successfully")
        
        # Calculate total steps
        total_steps = len(TABLE_FILES) + len(STORED_PROCEDURE_FILES) + len(TRIGGER_FILES)
        current_step = 0
        
        # Execute table files
        print_header("Creating Tables and Initial Data")
        for file_name in TABLE_FILES:
            current_step += 1
            file_path = SCHEMAS_DIR / file_name
            
            if not file_path.exists():
                print(f"✗ File not found: {file_path}")
                sys.exit(1)
            
            print_step(current_step, total_steps, f"Processing {file_name}")
            if not execute_sql_file(connection, file_path):
                print("\n✗ Failed to execute table file. Aborting.")
                sys.exit(1)
        
        # Execute stored procedure files
        print_header("Creating Stored Procedures")
        for file_name in STORED_PROCEDURE_FILES:
            current_step += 1
            file_path = SCHEMAS_DIR / file_name
            
            if not file_path.exists():
                print(f"✗ File not found: {file_path}")
                sys.exit(1)
            
            print_step(current_step, total_steps, f"Processing {file_name}")
            if not execute_sql_file(connection, file_path):
                print("\n✗ Failed to execute stored procedure file. Aborting.")
                sys.exit(1)
        
        # Execute trigger files
        print_header("Creating Activity Logging Triggers")
        for file_name in TRIGGER_FILES:
            current_step += 1
            file_path = SCHEMAS_DIR / file_name
            
            if not file_path.exists():
                print(f"✗ File not found: {file_path}")
                sys.exit(1)
            
            print_step(current_step, total_steps, f"Processing {file_name}")
            if not execute_sql_file(connection, file_path):
                print("\n✗ Failed to execute trigger file. Aborting.")
                sys.exit(1)
        
        # Verify database creation
        print_header("Verification")
        cursor = connection.cursor()
        
        # Check tables
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM information_schema.tables 
            WHERE table_schema = 'magic_auth'
        """)
        table_count = cursor.fetchone()['count']
        print(f"  Tables created: {table_count}")
        
        # Check stored procedures
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM information_schema.routines 
            WHERE routine_schema = 'magic_auth' AND routine_type = 'PROCEDURE'
        """)
        sp_count = cursor.fetchone()['count']
        print(f"  Stored procedures created: {sp_count}")
        
        # Check views
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM information_schema.views 
            WHERE table_schema = 'magic_auth'
        """)
        view_count = cursor.fetchone()['count']
        print(f"  Views created: {view_count}")
        
        # Check triggers
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM information_schema.triggers 
            WHERE trigger_schema = 'magic_auth'
        """)
        trigger_count = cursor.fetchone()['count']
        print(f"  Triggers created: {trigger_count}")
        
        cursor.close()
        connection.close()
        
        print_header("Database Creation Complete!")
        print("\n✓ Database 'magic_auth' has been created successfully!")
        print("\n  Initial Credentials:")
        print("    Username: root")
        print("    Password: admin123")
        print("    Email: root@system.local")
        print("\n  ⚠️  Please change the default password immediately!")
        
    except pymysql.Error as e:
        print(f"\n✗ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    create_database()
