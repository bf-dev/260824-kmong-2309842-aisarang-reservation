if(typeof NetFunnel == "object"){
    NetFunnel.SkinUtil.add('mcis',{ 
        prepareCallback:function(){
            var progress_print = document.getElementById("Progress_Print");
            progress_print.innerHTML="0 % (0/0) - 0 sec";
        },
        updateCallback:function(percent,nwait,totwait,timeleft){
            var progress_print = document.getElementById("Progress_Print");
            var prog=totwait - nwait;
            progress_print.innerHTML=percent+" % ("+prog+"/"+totwait+") - "+timeleft+" sec";
        },
        //PC 스킨
        htmlStr:
        	'<div id="NetFunnel_Skin_Top" style="background-color:#ffffff;border:1px solid #9ab6c4;width:580px;-moz-border-radius: 5px; -webkit-border-radius: 5px; -khtml-border-radius: 5px; border-radius: 5px;">'
			+ '<div style="background-color:#ffffff;border:6px solid #eaeff3;-moz-border-radius: 5px; -webkit-border-radius: 5px; -khtml-border-radius: 5px; border-radius: 5px;">'
			+ '<div style="padding-top:0px;padding-left:25px;padding-right:25px">'
			+ '<div style="text-align:left;font-size:16pt;color:#001f6c;height:22px;margin-top:10px;"><b>시간제 보육 예약 <span style="color:#013dc1"> 대기 중</span>입니다.</b></div>'
			+ '<div style="text-align:right;font-size:11pt;color:#4d4b4c;padding-top:4px;width:99%;height:17px" ><b>예상대기시간 : <span id="NetFunnel_Loading_Popup_TimeLeft" class="%H시간 %M분 %02S초^ ^false"></span></b></div>'
			+ '<div id="Progress_Print" style="display:none;position:absolute;left:0;top:100px;width:100%;text-align:center;font-size:17px;color:gray"></div> '
			+ '<div style="padding-top:6px;padding-bottom:6px;vertical-align:center;height:20px" id="NetFunnel_Loading_Popup_Progressbar"></div>'
			+ '<div style="background-color:#ededed;padding-bottom:8px;overflow:hidden">'
			+ '<div style="padding:10px;">'
			+ '<div style="text-align:left;font-size:13pt;color:#4d4b4c;padding:5px;height:60%;">현재 앞에 <b><span style="color:#2a509b"><span id="NetFunnel_Loading_Popup_Count" class="'+NetFunnel.TS_LIMIT_TEXT+'"></span></span></b> 명, 뒤에 <b><span style="color:#2a509b"><span id="NetFunnel_Loading_Popup_NextCnt" class="'+NetFunnel.TS_LIMIT_TEXT+'"></span></span></b> 명의 대기자가 있습니다.</br></br>'
			+ '<div style="text-align:left;font-size:13pt;color:#4d4b4c;height:10%;">현재 접속 사용자가 많아 대기 중이며, 잠시만 기다리시면 </div>'
			+ '<div style="text-align:left;font-size:13pt;color:#4d4b4c;height:10%;">예약이 완료됩니다.</div>'
			+ '<div style="text-align:left;font-size:12pt;color:#4d4b4c;height:10%;">*<b><span style="color: red;">시간당 인원이 초과</span>될 경우 예약이 불가할 수 있습니다.</b></div>'
			+ '<div style="text-align:center;font-size:10pt;color:#2a509b;padding-top:15px;">'
			+ '<b>※ 재접속하시면 대기시간이 더 길어집니다. <span id="NetFunnel_Countdown_Stop" style="cursor:pointer">[중지]</b>'
			+ '</div>'
			+ '</div>'
			+ '</div>'
			+ '</div>'
			+ '<div style="height:5px;"></div>'
			+ '</div>'
			+ '</div>'
			+ '</div>'
			
			//기존 PC 전용 스킨
			/*'<div id="NetFunnel_Skin_Top" style="position:relative;width:550px;height:150px;padding:68px 0 72px 0;font-family:Nanum Gothic;background-color:#ffffff;border:2px solid #006fb7;"> '
				+ '<div> '					
				+ '<strong style="position:absolute;left:0;top:0;display:block;width:100%;height:68px;font-weight:normal;background:#006db8;"> '
				+ '<p style="padding:24px 30px;margin:0 60px 0 0;text-align:left;font-size:20px;color:#fff;">현재 예약 이용자가 많아 <span style="font-weight:bold;">접속 대기 중</span>입니다.</p></strong> '
				+ '<p style="position:absolute;left:30px;top:90px;width:100%;color:#006db8;font-size:20px">대기 순서에 따라 <span style="color:#ff4a1a;">자동 접속</span>됩니다.</p> '
				+ '<p style="position:absolute;left:30px;top:130px;color:#006db8;font-size:17px">  예상 대기 시간 : <span id="NetFunnel_Loading_Popup_TimeLeft" style="color:#ff4a1a;"></span>'
				+ '&nbsp;/&nbsp;현재 대기순번 <span id="NetFunnel_Loading_Popup_Count" style="color:#ff4a1a;"></span>번째</p> '
				+ '<div style="position:absolute;left:0;bottom:0;width:100%;height:65px;background:#eff4f5;">'
				+ '<div style="padding:25px 30px 0 30px;color:#455251;font-size:13px;line-height:20px;">- 새로고침, 뒤로가기 또는 재접속하시면 대기시간이 더 길어집니다.</div>'
				+ '</div> '
				+ '<div id="Progress_Print" style="display:none;position:absolute;left:0;top:100px;width:100%;text-align:center;font-size:17px;color:gray"></div> '
				+ '</div> '
				+ '<div style="padding:90px 0 0 30px;width:490px" id="NetFunnel_Loading_Popup_Progressbar"> </div>'
				+ '<center><button id="NetFunnel_Countdown_Stop" style=" font-size: 15px;  padding: 5px 5px 5px 5px;color: #900; font-weight: bold;margin:15px;width:80px;">중지</button> </center>'
				+ '</div>'*/
			
    },'normal'); 

	//모바일 스킨
	NetFunnel.tstr = '\
		<div id="NetFunnel_Skin_Top" style="background-color:#ffffff;border:1px solid #9ab6c4;width:380px;-moz-border-radius: 5px; -webkit-border-radius: 5px; -khtml-border-radius: 5px; border-radius: 5px;">\
			<div style="background-color:#ffffff;border:6px solid #eaeff3;-moz-border-radius: 5px; -webkit-border-radius: 5px; -khtml-border-radius: 5px; border-radius: 5px;">\
				<div style="padding-top:0px;padding-left:25px;padding-right:25px">\
					<div style="text-align:left;font-size:12pt;color:#001f6c;height:22px;margin-top:10px;"><b>시간제보육 예약 <span style="color:#013dc1">대기 중</span>입니다.</b></div>\
					<div style="text-align:right;font-size:9pt;color:#4d4b4c;padding-top:4px;width:99%;height:17px" ><b>예상대기시간 : <span id="NetFunnel_Loading_Popup_TimeLeft" class="%H시간 %M분 %02S초^ ^false"></span></b></div>\
					<div style="padding-top:6px;padding-bottom:6px;vertical-align:center;height:20px" id="NetFunnel_Loading_Popup_Progressbar"></div>\
					<div style="background-color:#ededed;padding-bottom:8px;overflow:hidden">\
						<div style="padding:10px;> \
							<div style="text-align:left;font-size:8pt;color:#4d4b4c;padding:3px;height:20px;">현재 앞에 <b><span style="color:#2a509b"><span id="NetFunnel_Loading_Popup_Count" class="'+NetFunnel.TS_LIMIT_TEXT+'"></span></span></b> 명, 뒤에 <b><span style="color:#2a509b"><span id="NetFunnel_Loading_Popup_NextCnt" class="'+NetFunnel.TS_LIMIT_TEXT+'"></span></span></b> 명의 대기자가 있습니다.</br></br>\
							<div style="text-align:left;font-size:8pt;color:#4d4b4c;padding:3px;height:20px;">현재 접속 사용자가 많아 대기 중이며, 잠시만 기다리시면 </div>\
							<div style="text-align:left;font-size:8pt;color:#4d4b4c;padding:3px;height:20px;">예약이 완료됩니다.</div>\
							<div style="text-align:left;font-size:7pt;color:#4d4b4c;padding:3px;height:20px;">*<b><span style="color: red;">시간당 인원이 초과</span>될 경우 예약이 불가할 수 있습니다.</b></div>\
							<div style="text-align:center;font-size:9pt;color:#2a509b;padding-top:10px;">\
								<b>※ 재접속하시면 대기시간이 더 길어집니다. <span id="NetFunnel_Countdown_Stop" style="cursor:pointer">[중지]</b>\
							</div>\
						  </div>\
						</div>\
					</div>\
					<div style="height:5px;"></div>\
				</div>\
			</div>\
		</div>';
	
	NetFunnel.SkinUtil.add('mcis',{htmlStr:NetFunnel.tstr},'mobile');
}