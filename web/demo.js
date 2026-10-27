'use strict';
const video=document.getElementById('demo-video');
const audio=document.getElementById('demo-audio');
const status=document.getElementById('player-status');
const chapters=window.WorkbenchDemo?.chapters||[];
const time=value=>`${Math.floor(value/60)}:${String(Math.floor(value%60)).padStart(2,'0')}`;
const buttons=[];
for(const chapter of chapters) {
  const item=document.createElement('li');
  const button=document.createElement('button');
  button.className='chapter';button.dataset.color=chapter.color;
  button.setAttribute('aria-label',`${time(chapter.start)} · ${chapter.title}`);
  const stamp=document.createElement('time');stamp.textContent=time(chapter.start);
  const title=document.createElement('span');title.textContent=chapter.title;
  button.append(stamp,title);item.append(button);
  document.getElementById('chapters').append(item);buttons.push(button);
  button.onclick=()=>{
    const seek=()=>{
      video.currentTime=chapter.start;
      video.play().catch(error=>{
        if(error.name!=='AbortError' && audio.paused)
          status.textContent='Press Play on the video to continue from this chapter.';
      });
    };
    if(video.readyState>=1) seek();
    else video.addEventListener('loadedmetadata',seek,{once:true});
  };
  const section=document.createElement('section');
  const heading=document.createElement('h3');heading.textContent=`${time(chapter.start)} · ${chapter.title}`;
  const paragraph=document.createElement('p');paragraph.textContent=chapter.text;
  section.append(heading,paragraph);document.getElementById('transcript').append(section);
}
function currentChapter() {
  chapters.forEach((chapter,index)=>{
    const current=video.currentTime>=chapter.start&&video.currentTime<chapter.end;
    if(current) buttons[index].setAttribute('aria-current','true');
    else buttons[index].removeAttribute('aria-current');
  });
}
video.addEventListener('timeupdate',currentChapter);
video.addEventListener('play',()=>{audio.pause();status.textContent='';});
audio.addEventListener('play',()=>{video.pause();status.textContent='';});
for(const medium of [video,audio]) {
  medium.addEventListener('error',()=>{
    status.textContent='The media file could not be loaded. Keep the media folder beside this page, or use the download links.';
  });
}
window.addEventListener('pagehide',()=>{video.pause();audio.pause();});
currentChapter();
