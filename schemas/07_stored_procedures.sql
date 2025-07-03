-- 07_stored_procedures.sql
-- Stored Procedures for application logic (initial set)
-- MySQL Database

USE magic_auth;

DELIMITER $$

-- =====================================================
-- sp_list_users
-- -----------------------------------------------------
-- Returns a paginated list of users with optional
-- filtering by search term, user type, group, project
-- and active status. This procedure is designed to
-- replace the dynamic SQL previously constructed in
-- the application layer.
-- =====================================================
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
    -- Validate / normalise sort column & direction --------------------------------------
    SET @sort_col := CASE LOWER(p_sort_by)
        WHEN 'created_at'  THEN 'u.created_at'
        WHEN 'email'       THEN 'u.email'
        WHEN 'user_type'   THEN 'u.user_type'
        ELSE 'u.username' END;

    SET @dir := IF(LOWER(p_sort_order) = 'desc', 'DESC', 'ASC');

    -- Base query ------------------------------------------------------------------------
    SET @sql := CONCAT('SELECT u.id,
                               u.user_hash,
                               u.username,
                               u.email,
                               u.password_hash,
                               u.user_type,
                               u.assigned_project_id,
                               u.created_at,
                               u.is_active
                        FROM users u ');

    -- Conditional joins -----------------------------------------------------------------
    IF p_group_filter IS NOT NULL OR p_project_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql,
            'LEFT JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1\n',
            'LEFT JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1\n');
    END IF;

    IF p_project_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql,
            'LEFT JOIN user_group_projects ugp ON ug.id = ugp.user_group_id AND ugp.is_active = 1\n',
            'LEFT JOIN projects p ON ugp.project_id = p.id AND p.is_active = 1\n');
    END IF;

    -- WHERE clause ----------------------------------------------------------------------
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

    -- Final ordering & pagination -------------------------------------------------------
    SET @sql := CONCAT(@sql, 'GROUP BY u.id ORDER BY ', @sort_col, ' ', @dir,
                       ' LIMIT ', p_limit, ' OFFSET ', p_offset);

    -- Execute ---------------------------------------------------------------------------
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
END$$

DELIMITER ; 