-- ===================================================================================
-- USER MANAGEMENT STORED PROCEDURES
-- GROUPS OF GROUPS Architecture
-- ===================================================================================
-- This file contains all stored procedures related to user management:
-- - User authentication
-- - User CRUD operations
-- - User type management
-- - User status management
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- USER AUTHENTICATION
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_user_login$$
CREATE PROCEDURE sp_user_login(IN p_username_email VARCHAR(255))
BEGIN
    DECLARE v_resolved_user_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_identifier_normalized VARCHAR(255);

    SET v_identifier_normalized = LOWER(TRIM(p_username_email));

    -- Username resolution remains first so an email-shaped username cannot be
    -- shadowed by another account's activated email identity.
    SELECT id
      INTO v_resolved_user_id
    FROM users
    WHERE is_active = 1
      AND username = p_username_email
    LIMIT 1;

    -- Email login uses user_emails only. Legacy users.email is a compatibility
    -- shadow and must not grant login by itself.
    IF v_resolved_user_id IS NULL THEN
        SELECT u.id
          INTO v_resolved_user_id
        FROM user_emails ue
        JOIN users u ON u.id = ue.user_id
        WHERE u.is_active = 1
          AND ue.status = 'activated'
          AND ue.removed_at IS NULL
          AND ue.email_normalized = v_identifier_normalized
        ORDER BY ue.is_primary DESC, ue.activated_at ASC, ue.added_at ASC
        LIMIT 1;
    END IF;

    SELECT id, user_hash, username, email, password_hash, user_type, role_id, created_at, last_login, is_active
    FROM users
    WHERE id = v_resolved_user_id
      AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_update_last_login$$
CREATE PROCEDURE sp_update_last_login(IN p_user_id VARCHAR(64))
BEGIN
    UPDATE users SET last_login = NOW() WHERE id = p_user_id;
END$$

-- ===================================================================================
-- USER CRUD OPERATIONS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_user_by_id$$
CREATE PROCEDURE sp_get_user_by_id(IN p_user_id VARCHAR(64))
BEGIN
    SELECT id, user_hash, username, email, password_hash, user_type, role_id, created_at, last_login, updated_at, is_active
    FROM users WHERE id = p_user_id AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_by_hash$$
CREATE PROCEDURE sp_get_user_by_hash(IN p_user_hash VARCHAR(255), IN p_include_inactive TINYINT)
BEGIN
    IF p_include_inactive = 1 THEN
        SELECT id, user_hash, username, email, password_hash, user_type, role_id, created_at, last_login, updated_at, is_active
        FROM users WHERE user_hash = p_user_hash;
    ELSE
        SELECT id, user_hash, username, email, password_hash, user_type, role_id, created_at, last_login, updated_at, is_active
        FROM users WHERE user_hash = p_user_hash AND is_active = 1;
    END IF;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_type$$
CREATE PROCEDURE sp_get_user_type(IN p_user_id VARCHAR(64))
BEGIN
    SELECT user_type FROM users WHERE id = p_user_id AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_check_username_email_available$$
CREATE PROCEDURE sp_check_username_email_available(IN p_username_or_email VARCHAR(255))
BEGIN
    -- Compatibility inventory only. Email activation/reset flows must use
    -- user_emails lifecycle procedures instead of this availability oracle.
    SELECT COUNT(*) as count FROM users
    WHERE (username = p_username_or_email OR email = p_username_or_email) AND is_active = 1;
END$$

-- ===================================================================================
-- USER CREATION (TYPE-SPECIFIC)
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_create_consumer_user$$
CREATE PROCEDURE sp_create_consumer_user(
    IN p_user_id VARCHAR(64),
    IN p_user_hash VARCHAR(255),
    IN p_username VARCHAR(100),
    IN p_email VARCHAR(255),
    IN p_password_hash VARCHAR(255),
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO users (id, user_hash, username, email, password_hash, user_type, created_by, created_at)
    VALUES (p_user_id, p_user_hash, p_username, p_email, p_password_hash, 'consumer', p_created_by, NOW());
END$$

DROP PROCEDURE IF EXISTS sp_create_admin_user$$
CREATE PROCEDURE sp_create_admin_user(
    IN p_user_id VARCHAR(64),
    IN p_user_hash VARCHAR(255),
    IN p_username VARCHAR(100),
    IN p_email VARCHAR(255),
    IN p_password_hash VARCHAR(255),
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO users (id, user_hash, username, email, password_hash, user_type, created_by, created_at)
    VALUES (p_user_id, p_user_hash, p_username, p_email, p_password_hash, 'admin', p_created_by, NOW());
END$$

DROP PROCEDURE IF EXISTS sp_create_root_user$$
CREATE PROCEDURE sp_create_root_user(
    IN p_user_id VARCHAR(64),
    IN p_user_hash VARCHAR(255),
    IN p_username VARCHAR(100),
    IN p_email VARCHAR(255),
    IN p_password_hash VARCHAR(255),
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO users (id, user_hash, username, email, password_hash, user_type, created_by, created_at)
    VALUES (p_user_id, p_user_hash, p_username, p_email, p_password_hash, 'root', p_created_by, NOW());
END$$

-- ===================================================================================
-- USER UPDATES
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_update_user$$
CREATE PROCEDURE sp_update_user(
    IN p_user_id VARCHAR(64),
    IN p_username VARCHAR(100),
    IN p_email VARCHAR(255),
    IN p_password_hash VARCHAR(255),
    IN p_user_type VARCHAR(20)
)
BEGIN
    UPDATE users
    SET username = COALESCE(p_username, username),
        email = COALESCE(p_email, email),
        password_hash = COALESCE(p_password_hash, password_hash),
        user_type = COALESCE(p_user_type, user_type),
        updated_at = NOW()
    WHERE id = p_user_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_update_user_type$$
CREATE PROCEDURE sp_update_user_type(IN p_user_id VARCHAR(64), IN p_new_user_type VARCHAR(20))
BEGIN
    UPDATE users SET user_type = p_new_user_type, updated_at = NOW()
    WHERE id = p_user_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_update_password_hash$$
CREATE PROCEDURE sp_update_password_hash(IN p_user_id VARCHAR(64), IN p_new_password_hash VARCHAR(255))
BEGIN
    UPDATE users SET password_hash = p_new_password_hash, updated_at = NOW() WHERE id = p_user_id;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_change_user_password_if_hash_matches$$
CREATE PROCEDURE sp_change_user_password_if_hash_matches(
    IN p_user_id VARCHAR(64),
    IN p_expected_password_hash VARCHAR(255),
    IN p_new_password_hash VARCHAR(255)
)
BEGIN
    UPDATE users
    SET password_hash = p_new_password_hash,
        updated_at = NOW()
    WHERE id = p_user_id
      AND is_active = TRUE
      AND password_hash = p_expected_password_hash;

    SELECT ROW_COUNT() AS rows_affected;
END$$

-- ===================================================================================
-- USER DELETION
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_delete_user$$
CREATE PROCEDURE sp_delete_user(IN p_user_id VARCHAR(64))
BEGIN
    UPDATE users SET is_active = 0, updated_at = NOW() WHERE id = p_user_id AND is_active = 1;
    UPDATE user_group_members SET is_active = 0, removed_at = NOW() WHERE user_id = p_user_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

-- ===================================================================================
-- USER LISTING & SEARCH
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_list_users$$
CREATE PROCEDURE sp_list_users(
    IN p_limit INT,
    IN p_offset INT,
    IN p_sort_by VARCHAR(50),
    IN p_sort_order VARCHAR(4),
    IN p_search VARCHAR(255),
    IN p_user_type_filter VARCHAR(20),
    IN p_group_filter VARCHAR(255),
    IN p_project_filter VARCHAR(255),
    IN p_include_inactive BOOLEAN
)
BEGIN
    SET @sort_col := CASE LOWER(p_sort_by)
        WHEN 'created_at' THEN 'u.created_at'
        WHEN 'email' THEN 'u.email'
        WHEN 'user_type' THEN 'u.user_type'
        ELSE 'u.username' END;
    SET @dir := IF(LOWER(p_sort_order) = 'desc', 'DESC', 'ASC');
    
    SET @sql := CONCAT('SELECT DISTINCT u.id, u.user_hash, u.username, u.email, u.user_type, u.role_id, u.created_at, u.last_login, u.is_active FROM users u ');
    
    IF p_group_filter IS NOT NULL OR p_project_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql, 
            'LEFT JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1 ',
            'LEFT JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1 ');
    END IF;
    
    IF p_project_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql,
            'LEFT JOIN user_group_project_groups ugpg ON ug.id = ugpg.user_group_id AND ugpg.is_active = 1 ',
            'LEFT JOIN project_group_members pgm ON ugpg.project_group_id = pgm.project_group_id AND pgm.is_active = 1 ',
            'LEFT JOIN projects p ON pgm.project_id = p.id AND p.is_active = 1 ');
    END IF;
    
    SET @sql := CONCAT(@sql, 'WHERE 1=1 ');
    
    IF p_include_inactive = FALSE THEN
        SET @sql := CONCAT(@sql, 'AND u.is_active = 1 ');
    END IF;
    
    IF p_search IS NOT NULL THEN 
        SET @sql := CONCAT(@sql, 'AND (u.username LIKE ', QUOTE(CONCAT('%', p_search, '%')), 
                                 ' OR u.email LIKE ', QUOTE(CONCAT('%', p_search, '%')), ') '); 
    END IF;
    
    IF p_user_type_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql, 'AND u.user_type = ', QUOTE(p_user_type_filter), ' ');
    END IF;
    
    IF p_group_filter IS NOT NULL THEN 
        SET @sql := CONCAT(@sql, 'AND (ug.group_name = ', QUOTE(p_group_filter), 
                                 ' OR ug.group_hash = ', QUOTE(p_group_filter), ') '); 
    END IF;
    
    IF p_project_filter IS NOT NULL THEN 
        SET @sql := CONCAT(@sql, 'AND (p.project_name = ', QUOTE(p_project_filter), 
                                 ' OR p.project_hash = ', QUOTE(p_project_filter), ') '); 
    END IF;
    
    SET @sql := CONCAT(@sql, 'ORDER BY ', @sort_col, ' ', @dir, ' LIMIT ', p_limit, ' OFFSET ', p_offset);
    PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
END$$

DROP PROCEDURE IF EXISTS sp_list_users_with_access$$
CREATE PROCEDURE sp_list_users_with_access(
    IN p_limit INT,
    IN p_offset INT,
    IN p_sort_by VARCHAR(50),
    IN p_sort_order VARCHAR(4),
    IN p_search VARCHAR(255),
    IN p_user_type_filter VARCHAR(20),
    IN p_group_filter VARCHAR(255),
    IN p_project_filter VARCHAR(255),
    IN p_include_inactive BOOLEAN
)
BEGIN
    SET @sort_col := CASE LOWER(IFNULL(p_sort_by, ''))
        WHEN 'created_at' THEN 'u.created_at'
        WHEN 'email' THEN 'u.email'
        WHEN 'user_type' THEN 'u.user_type'
        WHEN 'last_login' THEN 'u.last_login'
        ELSE 'u.username' END;
    SET @dir := IF(LOWER(p_sort_order) = 'desc', 'DESC', 'ASC');

    SET @sql := CONCAT(
        'SELECT ',
        'u.id, u.user_hash, u.username, u.email, u.user_type, u.created_at, u.last_login, u.is_active, ',
        'COALESCE((SELECT JSON_ARRAYAGG(JSON_OBJECT(',
            '''group_hash'', ug.group_hash, ',
            '''group_name'', ug.group_name, ',
            '''group_description'', ug.group_description, ',
            '''assigned_at'', ugm.assigned_at',
        ')) ',
        'FROM user_group_members ugm ',
        'JOIN user_groups ug ON ugm.user_group_id = ug.id ',
        'WHERE ugm.user_id = u.id AND ugm.is_active = 1 AND ug.is_active = 1',
        '), JSON_ARRAY()) AS groups_json, ',
        'COALESCE((SELECT JSON_ARRAYAGG(JSON_OBJECT(',
            '''project_hash'', sub.project_hash, ',
            '''project_name'', sub.project_name, ',
            '''project_group'', sub.group_name',
        ')) FROM (SELECT DISTINCT p.project_hash, p.project_name, pg.group_name ',
        'FROM user_group_members ugm2 ',
        'JOIN user_group_project_groups ugpg ON ugm2.user_group_id = ugpg.user_group_id ',
        'JOIN project_groups pg ON ugpg.project_group_id = pg.id ',
        'JOIN project_group_members pgm ON pg.id = pgm.project_group_id ',
        'JOIN projects p ON pgm.project_id = p.id ',
        'WHERE ugm2.user_id = u.id ',
          'AND ugm2.is_active = 1 AND ugpg.is_active = 1 AND pgm.is_active = 1 AND p.is_active = 1) sub',
        '), JSON_ARRAY()) AS projects_json ',
        'FROM users u WHERE 1=1 '
    );

    IF p_include_inactive = FALSE THEN
        SET @sql := CONCAT(@sql, 'AND u.is_active = 1 ');
    END IF;

    IF p_search IS NOT NULL THEN
        SET @sql := CONCAT(@sql, 'AND (u.username LIKE ', QUOTE(CONCAT('%', p_search, '%')),
                          ' OR u.email LIKE ', QUOTE(CONCAT('%', p_search, '%')), ') ');
    END IF;

    IF p_user_type_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql, 'AND u.user_type = ', QUOTE(p_user_type_filter), ' ');
    END IF;

    IF p_group_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql,
            'AND EXISTS (',
                'SELECT 1 FROM user_group_members ugm_f ',
                'JOIN user_groups ug_f ON ugm_f.user_group_id = ug_f.id ',
                'WHERE ugm_f.user_id = u.id AND ugm_f.is_active = 1 AND ug_f.is_active = 1 ',
                'AND (ug_f.group_name = ', QUOTE(p_group_filter), ' OR ug_f.group_hash = ', QUOTE(p_group_filter), ')',
            ') ');
    END IF;

    IF p_project_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql,
            'AND EXISTS (',
                'SELECT 1 FROM user_group_members ugm_p ',
                'JOIN user_group_project_groups ugpg_p ON ugm_p.user_group_id = ugpg_p.user_group_id ',
                'JOIN project_group_members pgm_p ON ugpg_p.project_group_id = pgm_p.project_group_id ',
                'JOIN projects p_p ON pgm_p.project_id = p_p.id ',
                'WHERE ugm_p.user_id = u.id AND ugm_p.is_active = 1 AND ugpg_p.is_active = 1 ',
                'AND pgm_p.is_active = 1 AND p_p.is_active = 1 ',
                'AND (p_p.project_name = ', QUOTE(p_project_filter), ' OR p_p.project_hash = ', QUOTE(p_project_filter), ')',
            ') ');
    END IF;

    SET @sql := CONCAT(@sql, 'ORDER BY ', @sort_col, ' ', @dir, ' LIMIT ', p_limit, ' OFFSET ', p_offset);
    PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
END$$

DROP PROCEDURE IF EXISTS sp_count_users$$
CREATE PROCEDURE sp_count_users(IN p_user_type VARCHAR(20), IN p_include_inactive BOOLEAN)
BEGIN
    IF p_user_type IS NOT NULL THEN
        IF p_include_inactive THEN
            SELECT COUNT(*) as count FROM users WHERE user_type = p_user_type;
        ELSE
            SELECT COUNT(*) as count FROM users WHERE user_type = p_user_type AND is_active = 1;
        END IF;
    ELSE
        IF p_include_inactive THEN
            SELECT COUNT(*) as count FROM users;
        ELSE
            SELECT COUNT(*) as count FROM users WHERE is_active = 1;
        END IF;
    END IF;
END$$

DROP PROCEDURE IF EXISTS sp_search_users$$
CREATE PROCEDURE sp_search_users(IN p_search_term VARCHAR(255), IN p_user_type VARCHAR(20), IN p_limit INT)
BEGIN
    IF p_user_type IS NOT NULL THEN
        SELECT id, user_hash, username, email, user_type, role_id, created_at, last_login, is_active
        FROM users
        WHERE is_active = 1
          AND (username LIKE CONCAT('%', p_search_term, '%') OR email LIKE CONCAT('%', p_search_term, '%'))
          AND user_type = p_user_type
        ORDER BY username ASC LIMIT p_limit;
    ELSE
        SELECT id, user_hash, username, email, user_type, role_id, created_at, last_login, is_active
        FROM users
        WHERE is_active = 1
          AND (username LIKE CONCAT('%', p_search_term, '%') OR email LIKE CONCAT('%', p_search_term, '%'))
        ORDER BY username ASC LIMIT p_limit;
    END IF;
END$$

-- ===================================================================================
-- USER STATUS MANAGEMENT
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_user_status$$
CREATE PROCEDURE sp_get_user_status(IN p_user_id VARCHAR(64))
BEGIN
    SELECT is_active FROM users WHERE id = p_user_id;
END$$

DROP PROCEDURE IF EXISTS sp_set_user_status$$
CREATE PROCEDURE sp_set_user_status(IN p_user_id VARCHAR(64), IN p_is_active BOOLEAN)
BEGIN
    UPDATE users SET is_active = p_is_active, updated_at = NOW() WHERE id = p_user_id;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_get_recent_users_count$$
CREATE PROCEDURE sp_get_recent_users_count(IN p_days INT)
BEGIN
    SELECT COUNT(*) as count FROM users
    WHERE created_at >= DATE_SUB(NOW(), INTERVAL p_days DAY) AND is_active = 1;
END$$

DELIMITER ;

-- ===================================================================================
-- USER MANAGEMENT PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'User management stored procedures created!' as status,
       'Groups of Groups architecture applied' as details;
