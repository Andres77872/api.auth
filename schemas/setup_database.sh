#!/bin/bash

# Enhanced 3-Tier User Type Multi-Project Authentication Database Setup Script
# This script creates the database and all necessary tables with initial data

echo "=== Enhanced Authentication Database Setup ==="
echo

# Check if MySQL is available
if ! command -v mysql &> /dev/null; then
    echo "ERROR: MySQL client not found. Please install MySQL client first."
    exit 1
fi

# Get MySQL credentials
read -p "Enter MySQL username (default: root): " MYSQL_USER
MYSQL_USER=${MYSQL_USER:-root}

read -sp "Enter MySQL password: " MYSQL_PASS
echo

# Optional: Get MySQL host
read -p "Enter MySQL host (default: localhost): " MYSQL_HOST
MYSQL_HOST=${MYSQL_HOST:-localhost}

# Optional: Get MySQL port
read -p "Enter MySQL port (default: 3306): " MYSQL_PORT
MYSQL_PORT=${MYSQL_PORT:-3306}

echo
echo "Connecting to MySQL as $MYSQL_USER@$MYSQL_HOST:$MYSQL_PORT..."
echo

# Function to execute SQL file
execute_sql() {
    local file=$1
    local database=$2
    
    echo "Executing $file..."
    
    if [ -z "$database" ]; then
        mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASS" < "$file"
    else
        mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASS" "$database" < "$file"
    fi
    
    if [ $? -eq 0 ]; then
        echo "✓ $file executed successfully"
    else
        echo "✗ Error executing $file"
        exit 1
    fi
    echo
}

# Execute SQL files in order
echo "=== Step 1: Creating Database ==="
execute_sql "01_create_database.sql"

echo "=== Step 2: Creating Tables ==="
execute_sql "02_create_tables.sql" "auth_system"

echo "=== Step 3: Adding Constraints ==="
execute_sql "03_add_constraints.sql" "auth_system"

# Ask if user wants to initialize with default data
echo
read -p "Do you want to initialize with default data? (y/N): " INIT_DATA

if [[ $INIT_DATA =~ ^[Yy]$ ]]; then
    echo "=== Step 4: Initializing Default Data ==="
    execute_sql "04_initialize_data.sql" "auth_system"
    
    echo
    echo "=== Default Users Created ==="
    echo "Username: root    | Password: admin123 | Type: Root User"
    echo "Username: admin   | Password: admin123 | Type: Admin User"
    echo "Username: user    | Password: user123  | Type: Consumer User"
    echo
    echo "⚠️  IMPORTANT: Change these passwords immediately!"
else
    echo "=== Skipping Default Data Initialization ==="
fi

# Ask if user wants to add performance optimizations
echo
read -p "Do you want to add performance optimization indexes and procedures? (Y/n): " ADD_PERF

if [[ ! $ADD_PERF =~ ^[Nn]$ ]]; then
    echo "=== Step 5: Adding Performance Optimizations ==="
    execute_sql "05_performance_optimization.sql" "auth_system"
    echo "Performance optimizations added successfully!"
else
    echo "=== Skipping Performance Optimizations ==="
fi

echo
echo "=== Database Setup Complete ==="
echo
echo "Next steps:"
echo "1. Change default passwords if you initialized with default data"
echo "2. Create your first project using the root account"
echo "3. Set up proper backup procedures"
echo "4. Configure your application to connect to the 'auth_system' database"
echo
echo "For more information, see README.md" 