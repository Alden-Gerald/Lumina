function formatDuration(value){
  const number=Number(value),total=Number.isFinite(number)?Math.max(0,Math.floor(number)):0;
  const hours=Math.floor(total/3600),minutes=Math.floor(total%3600/60),seconds=total%60;
  if(hours)return `${hours}hr ${minutes}min ${seconds}sec`;
  if(minutes)return `${minutes}m ${seconds}sec`;
  return `${seconds}s`;
}
if(typeof module==='object'&&module.exports)module.exports=formatDuration;
