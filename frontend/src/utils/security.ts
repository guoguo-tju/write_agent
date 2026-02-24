/**
 * 安全工具函数
 */

/**
 * 转义 HTML 特殊字符，防止 XSS 攻击
 * 注意：React 默认使用 {} 语法时已经自动转义，此函数主要用于需要使用 dangerouslySetInnerHTML 的场景
 */
export const escapeHtml = (text: string): string => {
  const map: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  };
  return text.replace(/[&<>"']/g, (char) => map[char]);
};
