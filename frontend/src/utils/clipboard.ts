/**
 * 剪贴板写入工具：兼容非安全上下文（HTTP IP 直连）。
 *
 * 背景（试用反馈）：navigator.clipboard 仅在 secure context（HTTPS / localhost）
 * 可用，生产经 http://IP 访问时为 undefined，所有"复制"按钮静默失效。
 * 这里统一封装：优先用异步 Clipboard API，不可用或失败时降级为
 * 临时 textarea + document.execCommand('copy') 的传统方案。
 *
 * 创建日期：2026-06-13
 * author: sunshengxian
 */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  // 安全上下文优先走标准 Clipboard API。
  if (typeof navigator !== 'undefined' && navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // 失败（如权限被拒）继续走降级方案。
    }
  }
  // 降级：构造离屏 textarea 选中后 execCommand 复制；同步执行不影响调用方 await。
  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    // 离屏且只读：避免页面滚动跳动与移动端拉起键盘。
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(textarea);
    return ok;
  } catch {
    return false;
  }
}
