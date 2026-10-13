-- Serialize group graph changes until their owning transaction commits.
-- Triggers cover direct SQL as well as every stored-procedure/provisioning writer.
USE magic_auth;
DELIMITER //

DROP TRIGGER IF EXISTS trg_group_scope_user_groups_insert//
CREATE TRIGGER trg_group_scope_user_groups_insert BEFORE INSERT ON user_groups FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_user_groups_update//
CREATE TRIGGER trg_group_scope_user_groups_update BEFORE UPDATE ON user_groups FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_user_groups_delete//
CREATE TRIGGER trg_group_scope_user_groups_delete BEFORE DELETE ON user_groups FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_project_groups_insert//
CREATE TRIGGER trg_group_scope_project_groups_insert BEFORE INSERT ON project_groups FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_project_groups_update//
CREATE TRIGGER trg_group_scope_project_groups_update BEFORE UPDATE ON project_groups FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_project_groups_delete//
CREATE TRIGGER trg_group_scope_project_groups_delete BEFORE DELETE ON project_groups FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_user_group_members_insert//
CREATE TRIGGER trg_group_scope_user_group_members_insert BEFORE INSERT ON user_group_members FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_user_group_members_update//
CREATE TRIGGER trg_group_scope_user_group_members_update BEFORE UPDATE ON user_group_members FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_user_group_members_delete//
CREATE TRIGGER trg_group_scope_user_group_members_delete BEFORE DELETE ON user_group_members FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_project_group_members_insert//
CREATE TRIGGER trg_group_scope_project_group_members_insert BEFORE INSERT ON project_group_members FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_project_group_members_update//
CREATE TRIGGER trg_group_scope_project_group_members_update BEFORE UPDATE ON project_group_members FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_project_group_members_delete//
CREATE TRIGGER trg_group_scope_project_group_members_delete BEFORE DELETE ON project_group_members FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_user_group_project_groups_insert//
CREATE TRIGGER trg_group_scope_user_group_project_groups_insert BEFORE INSERT ON user_group_project_groups FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_user_group_project_groups_update//
CREATE TRIGGER trg_group_scope_user_group_project_groups_update BEFORE UPDATE ON user_group_project_groups FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_user_group_project_groups_delete//
CREATE TRIGGER trg_group_scope_user_group_project_groups_delete BEFORE DELETE ON user_group_project_groups FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_users_update//
CREATE TRIGGER trg_group_scope_users_update BEFORE UPDATE ON users FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    IF NOT (OLD.user_type <=> NEW.user_type) OR NOT (OLD.is_active <=> NEW.is_active) THEN
        SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
        IF v_group_graph_lock IS NULL THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
        END IF;
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_users_delete//
CREATE TRIGGER trg_group_scope_users_delete BEFORE DELETE ON users FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_projects_update//
CREATE TRIGGER trg_group_scope_projects_update BEFORE UPDATE ON projects FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    IF NOT (OLD.is_active <=> NEW.is_active) OR NOT (OLD.archived <=> NEW.archived) THEN
        SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
        IF v_group_graph_lock IS NULL THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
        END IF;
    END IF;
END//

DROP TRIGGER IF EXISTS trg_group_scope_projects_delete//
CREATE TRIGGER trg_group_scope_projects_delete BEFORE DELETE ON projects FOR EACH ROW
BEGIN
    DECLARE v_group_graph_lock INT DEFAULT NULL;
    SELECT id INTO v_group_graph_lock FROM group_graph_lock WHERE id = 1 FOR UPDATE;
    IF v_group_graph_lock IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Group graph lock is not initialized';
    END IF;
END//

DELIMITER ;
