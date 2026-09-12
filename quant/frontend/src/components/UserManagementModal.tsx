import { useCallback, useEffect, useMemo, useState } from "react";
import { createAdminUser, deleteAdminUser, fetchAdminUsers, updateAdminUser } from "../api/auth";
import type { AuthUser } from "../api/auth";

interface Props {
  onClose: () => void;
}

type DraftUser = {
  username: string;
  password: string;
  expires_at: string;
  banned: boolean;
};

type NewUserDraft = {
  username: string;
  password: string;
  expires_at: string;
};

function formatTime(value?: string) {
  if (!value) return "永久";
  const date = new Date(value.replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function toDatetimeLocal(value?: string) {
  if (!value) return "";
  const normalized = value.replace(" ", "T");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return normalized.slice(0, 16);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function fromDatetimeLocal(value: string) {
  return value ? `${value.replace("T", " ")}:00` : null;
}

function getUserStatusLabel(user: AuthUser, draft?: DraftUser) {
  if (draft?.banned || user.status === "banned") return "已封禁";
  if (user.status === "expired") return "已过期";
  return "正常";
}

export default function UserManagementModal({ onClose }: Props) {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [drafts, setDrafts] = useState<Record<string, DraftUser>>({});
  const [newUser, setNewUser] = useState<NewUserDraft>({ username: "", password: "", expires_at: "" });
  const [loading, setLoading] = useState(true);
  const [savingUser, setSavingUser] = useState("");
  const [deletingUser, setDeletingUser] = useState("");
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState("");

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setMessage("");
    const res = await fetchAdminUsers();
    if (res.success && res.data) {
      setUsers(res.data);
      setDrafts(
        Object.fromEntries(
          res.data.map((user) => [
            user.username,
            {
              username: user.username,
              password: "",
              expires_at: toDatetimeLocal(user.expires_at),
              banned: user.status === "banned",
            },
          ])
        )
      );
    } else {
      setMessage(res.message || "用户列表加载失败");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const totals = useMemo(() => {
    return users.reduce(
      (acc, user) => {
        acc.total += 1;
        if ((user.role || "").toLowerCase() === "trial") acc.trial += 1;
        if ((drafts[user.username]?.banned ?? user.status === "banned")) acc.banned += 1;
        return acc;
      },
      { total: 0, trial: 0, banned: 0 }
    );
  }, [drafts, users]);

  const patchDraft = (username: string, patch: Partial<DraftUser>) => {
    setDrafts((prev) => ({
      ...prev,
      [username]: {
        username: prev[username]?.username || username,
        password: prev[username]?.password || "",
        expires_at: prev[username]?.expires_at || "",
        banned: prev[username]?.banned || false,
        ...patch,
      },
    }));
  };

  const handleCreate = async () => {
    if (!newUser.username.trim() || !newUser.password) {
      setMessage("请输入用户名和密码");
      return;
    }
    setCreating(true);
    setMessage("");
    const res = await createAdminUser({
      username: newUser.username.trim(),
      password: newUser.password,
      expires_at: fromDatetimeLocal(newUser.expires_at),
    });
    if (res.success && res.data) {
      setUsers((prev) => [res.data!, ...prev]);
      setDrafts((prev) => ({
        ...prev,
        [res.data!.username]: {
          username: res.data!.username,
          password: "",
          expires_at: toDatetimeLocal(res.data!.expires_at),
          banned: res.data!.status === "banned",
        },
      }));
      setNewUser({ username: "", password: "", expires_at: "" });
      setMessage(`${res.data.username} 已新增`);
    } else {
      setMessage(res.message || "新增用户失败");
    }
    setCreating(false);
  };

  const handleSave = async (user: AuthUser) => {
    const draft = drafts[user.username] || { username: user.username, password: "", expires_at: "", banned: false };
    setSavingUser(user.username);
    setMessage("");
    const res = await updateAdminUser(user.username, {
      username: draft.username.trim(),
      password: draft.password,
      expires_at: fromDatetimeLocal(draft.expires_at),
      banned: draft.banned,
    });
    if (res.success && res.data) {
      setUsers((prev) => prev.map((item) => (item.username === user.username ? res.data! : item)));
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[user.username];
        next[res.data!.username] = {
          username: res.data!.username,
          password: "",
          expires_at: toDatetimeLocal(res.data!.expires_at),
          banned: res.data!.status === "banned",
        };
        return next;
      });
      setMessage(`${res.data.username} 已更新`);
    } else {
      setMessage(res.message || "保存失败");
    }
    setSavingUser("");
  };

  const handleDelete = async (user: AuthUser) => {
    if (user.username.toLowerCase() === "vk") return;
    const confirmed = window.confirm(`确定删除用户 ${user.username} 吗？删除后该账号将无法登录。`);
    if (!confirmed) return;
    setDeletingUser(user.username);
    setMessage("");
    const res = await deleteAdminUser(user.username);
    if (res.success) {
      setUsers((prev) => prev.filter((item) => item.username !== user.username));
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[user.username];
        return next;
      });
      setMessage(`${user.username} 已删除`);
    } else {
      setMessage(res.message || "删除用户失败");
    }
    setDeletingUser("");
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="user-management-modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel-card-header user-management-header">
          <div>
            <h3>用户管理</h3>
            <div className="panel-card-meta">
              共 {totals.total} 个用户，临时 {totals.trial} 个，封禁 {totals.banned} 个
            </div>
          </div>
          <div className="user-management-actions">
            <button className="toggle-btn" onClick={loadUsers} type="button" disabled={loading}>
              刷新
            </button>
            <button className="modal-close-btn" onClick={onClose} type="button">
              关闭
            </button>
          </div>
        </div>

        {message && <div className="login-message">{message}</div>}

        <div className="user-create-panel">
          <label className="user-management-field">
            <span>新用户名</span>
            <input
              className="pretty-input"
              value={newUser.username}
              onChange={(event) => setNewUser((prev) => ({ ...prev, username: event.target.value }))}
            />
          </label>
          <label className="user-management-field">
            <span>初始密码</span>
            <input
              className="pretty-input"
              type="password"
              value={newUser.password}
              onChange={(event) => setNewUser((prev) => ({ ...prev, password: event.target.value }))}
            />
          </label>
          <label className="user-management-field">
            <span>过期时间</span>
            <input
              className="user-expiry-input"
              type="datetime-local"
              value={newUser.expires_at}
              onChange={(event) => setNewUser((prev) => ({ ...prev, expires_at: event.target.value }))}
            />
          </label>
          <button
            className="toggle-btn active"
            type="button"
            onClick={handleCreate}
            disabled={creating}
          >
            {creating ? "新增中..." : "新增用户"}
          </button>
        </div>

        <div className="user-management-table-wrap">
          <table className="user-management-table">
            <thead>
              <tr>
                <th>用户名</th>
                <th>新密码</th>
                <th>类型</th>
                <th>状态</th>
                <th>注册时间</th>
                <th>登录时间</th>
                <th>过期时间</th>
                <th>封禁</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={9} className="user-management-empty">正在加载...</td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={9} className="user-management-empty">暂无用户</td>
                </tr>
              ) : (
                users.map((user) => {
                  const draft = drafts[user.username] || { username: user.username, password: "", expires_at: "", banned: user.status === "banned" };
                  const isAdmin = user.username.toLowerCase() === "vk";
                  return (
                    <tr key={user.username}>
                      <td>
                        <input
                          className="user-text-input"
                          value={draft.username}
                          disabled={isAdmin}
                          onChange={(event) => patchDraft(user.username, { username: event.target.value })}
                          aria-label={`${user.username} 用户名`}
                        />
                        {user.must_change_credentials && <span className="user-management-tag">待改密</span>}
                      </td>
                      <td>
                        <input
                          className="user-text-input"
                          type="password"
                          value={draft.password}
                          placeholder="留空不改"
                          onChange={(event) => patchDraft(user.username, { password: event.target.value })}
                          aria-label={`${user.username} 新密码`}
                        />
                      </td>
                      <td>{user.role || "user"}</td>
                      <td>
                        <span className={`user-status status-${draft.banned ? "banned" : user.status || "active"}`}>
                          {getUserStatusLabel(user, draft)}
                        </span>
                      </td>
                      <td>{formatTime(user.created_at)}</td>
                      <td>{user.last_login_at ? formatTime(user.last_login_at) : "未登录"}</td>
                      <td>
                        <input
                          className="user-expiry-input"
                          type="datetime-local"
                          value={draft.expires_at}
                          onChange={(event) => patchDraft(user.username, { expires_at: event.target.value })}
                          aria-label={`${user.username} 过期时间`}
                        />
                        <button
                          className="user-expiry-clear"
                          type="button"
                          onClick={() => patchDraft(user.username, { expires_at: "" })}
                        >
                          永久
                        </button>
                      </td>
                      <td>
                        <label className="user-ban-toggle">
                          <input
                            type="checkbox"
                            checked={draft.banned}
                            disabled={isAdmin}
                            onChange={(event) => patchDraft(user.username, { banned: event.target.checked })}
                          />
                          <span>{draft.banned ? "是" : "否"}</span>
                        </label>
                      </td>
                      <td>
                        <div className="user-row-actions">
                          <button
                            className="toggle-btn active"
                            type="button"
                            onClick={() => handleSave(user)}
                            disabled={savingUser === user.username || deletingUser === user.username}
                          >
                            {savingUser === user.username ? "保存中..." : "保存"}
                          </button>
                          <button
                            className="user-delete-btn"
                            type="button"
                            onClick={() => handleDelete(user)}
                            disabled={isAdmin || deletingUser === user.username || savingUser === user.username}
                          >
                            {deletingUser === user.username ? "删除中..." : "删除"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
