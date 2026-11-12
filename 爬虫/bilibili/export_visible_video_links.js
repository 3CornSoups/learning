(() => {
  if (!/(^|\.)bilibili\.com$/i.test(location.hostname)) {
    alert('请先打开B站UP主投稿页，等视频卡片加载完成，再点击这个书签。');
    return;
  }
  const urls = [...new Set(Array.from(document.querySelectorAll('a[href]'), a => a.href)
    .filter(href => /^https?:\/\/(www\.)?bilibili\.com\/video\/BV[0-9A-Za-z]{10}(?:[/?#]|$)/.test(href))
    .map(href => 'https://www.bilibili.com/video/' + href.match(/\/video\/(BV[0-9A-Za-z]{10})/)[1] + '/'))];
  if (!urls.length) {
    alert('本页尚未加载出视频链接，请等卡片显示后再试。');
    return;
  }
  const blob = new Blob(['\ufeff' + urls.join('\n') + '\n'], {type: 'text/plain;charset=utf-8'});
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = 'bilibili_video_links_' + new Date().toISOString().slice(0,10) + '.txt';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
})();