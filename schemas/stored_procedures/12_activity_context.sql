-- ===================================================================================
-- Activity Context Management - User Context for Triggers
-- ===================================================================================
-- Provides mechanism to set/get user context for activity logging triggers
-- Uses MySQL session variables to pass application context to triggers
-- ===================================================================================

USE magic_auth;

DELIMITER //

-- ===================================================================================
-- SP: SET ACTIVITY CONTEXT
-- ===================================================================================
-- Sets the current user context for activity logging
-- Must be called by application before any operation that should be logged
-- The trigger will read these variables to log who performed the action

DROP PROCEDURE IF EXISTS sp_set_activity_context//
CREATE PROCEDURE sp_set_activity_context(
    IN p_user_id VARCHAR(64),
    IN p_ip_address VARCHAR(45),
    IN p_user_agent TEXT
)
BEGIN
    -- Set session variables that triggers can read
    SET @activity_user_id = p_user_id;
    SET @activity_ip_address = p_ip_address;
    SET @activity_user_agent = p_user_agent;
    
    SELECT 'Activity context set' as status;
END//

-- ===================================================================================
-- SP: CLEAR ACTIVITY CONTEXT
-- ===================================================================================
-- Clears the activity context (optional, for cleanup)

DROP PROCEDURE IF EXISTS sp_clear_activity_context//
CREATE PROCEDURE sp_clear_activity_context()
BEGIN
    SET @activity_user_id = NULL;
    SET @activity_ip_address = NULL;
    SET @activity_user_agent = NULL;
    
    SELECT 'Activity context cleared' as status;
END//

-- ===================================================================================
-- SP: GET ACTIVITY CONTEXT
-- ===================================================================================
-- Gets current activity context (for debugging)

DROP PROCEDURE IF EXISTS sp_get_activity_context//
CREATE PROCEDURE sp_get_activity_context()
BEGIN
    SELECT 
        @activity_user_id as user_id,
        @activity_ip_address as ip_address,
        @activity_user_agent as user_agent;
END//

-- ===================================================================================
-- HELPER FUNCTION: GET CONTEXT USER ID
-- ===================================================================================
-- Function to get user ID from context, with fallback logic

DROP FUNCTION IF EXISTS fn_get_context_user_id//
CREATE FUNCTION fn_get_context_user_id(
    p_created_by VARCHAR(64),
    p_updated_by VARCHAR(64),
    p_assigned_by VARCHAR(64)
)
RETURNS VARCHAR(64)
DETERMINISTIC
READS SQL DATA
BEGIN
    -- Priority order:
    -- 1. Session context (@activity_user_id)
    -- 2. created_by/updated_by/assigned_by from the record
    -- 3. NULL (system action)
    
    IF @activity_user_id IS NOT NULL THEN
        RETURN @activity_user_id;
    END IF;
    
    IF p_assigned_by IS NOT NULL THEN
        RETURN p_assigned_by;
    END IF;
    
    IF p_updated_by IS NOT NULL THEN
        RETURN p_updated_by;
    END IF;
    
    IF p_created_by IS NOT NULL THEN
        RETURN p_created_by;
    END IF;
    
    RETURN NULL;
END//

DELIMITER ;

-- ===================================================================================
-- CONTEXT MANAGEMENT PROCEDURES CREATED
-- ===================================================================================
SELECT 'Activity context management procedures created!' as status,
       '3 procedures + 1 function for user context tracking' as details;
