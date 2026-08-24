var vidResult = "";

function init()
{
  initForm();
  numbering();
  initKeyboard();
}

function sumCheckbox (aCheckbox)
{
  var aIter;
  var aTotal = 0;

  for (aIter = 0;aIter < aCheckbox.length;aIter++)
  {
    if (aCheckbox[aIter].checked)
      aTotal += parseInt (aCheckbox[aIter].value);
  }

  return aTotal;
}

function numbering ()
{
  var aElements = document.getElementsByTagName('h3');

  for (i = 0 ; i < aElements.length ; i++)
  {
    aElements[i].innerHTML = (i + 1) + ". " + aElements[i].innerHTML;
    aElements.id = "elem" + (i + 1);
  }
}

function initForm ()
{
  if (AnySign.mFinancialType) {
    document.getElementById("aFinalcial").value = "1(EN_KEB)";
  } else {
    document.getElementById("aFinalcial").value = "0(EN_FINAANCIAL)";
  }

  if (AnySign.mShowLocationDialog) {
    document.getElementById("aShowDialog").value = AnySign.mShowLocationDialog + " (저장매체 UI보임)";
  } else {
    document.getElementById("aShowDialog").value = AnySign.mShowLocationDialog + " (저장매체 UI안보임)";
  }
}

function initKeyboard()
{
  document.getElementById("Enable_Transkey").value = AnySign.mTransKeyEnable;
  document.getElementById("Enable_Openkeyboard").value = AnySign.mOpenkeyboardEnable;
  document.getElementById("Enable_TouchEnKey").value = AnySign.mTouchEnKeyEnable;
  document.getElementById("Enable_KDefense").value = AnySign.mKDefenseEnable;
  document.getElementById("Enable_VKeypad").value = AnySign.mVKeypadEnable;

  // check Module Load
  if (navigator.userAgent.indexOf("MSIE") >= 0)
  {
    document.getElementById("Load_TouchEnKey").innerHTML = document.TouchEnKey != null && typeof(document.TouchEnKey) != "undefined" && document.TouchEnKey.object != null;
    document.getElementById("Load_KDefense").innerHTML = document.kdefense != null && typeof(document.kdefense) != "undefined" && document.kdefense.object != null;
  }
  else
  {
    document.getElementById("Load_TouchEnKey").innerHTML = document.getElementById("TouchEnKey") != null && typeof(document.getElementById("TouchEnKey")) != "undefined";

    var lsslmimeType = navigator.mimeTypes["application/lssl-plugin"];
    if( lsslmimeType == null || lsslmimeType == "undefined")
      document.getElementById("Load_KDefense").innerHTML = false;
    else
      document.getElementById("Load_KDefense").innerHTML = true;
  }

  // init K-Defense
  if (document.getElementById("Enable_KDefense").value == "true")
    initKDefenseE2E();
}

function initKDefenseE2E()
{
  aSessionKey = AnySign.GenerateRandom(16, 0);
  regFormEle_K("text_field1","none");
  regFormEle_K("text_field2","none");
  Get_Xgate_addr();
}

// XecureWeb PlugIn Install
function onFinishXWInstall() {
  if(!AnySign.IsNeedUpdate())
  {
  }
}

// XCS PlugIn Install
function onFinishXCSInstall() {
  if(!XecureCertShare.IsNeedUpdate())
  {

  }
}

// 공인인증서 종료 callback 여기에서 submit을 해준다.
function SignDataCMS_callback (aResult)
{
    document.getElementsByName (xecureFormName)[0].aResult.value = aResult;

    var frmLoginCert = document.getElementById(xecureFormName);

    frmLoginCert.submit();
}

// 공인인증서 종료 callback 여기에서 submit을 해준다.
function SignDataWithVID_callback (aResult)
{
    document.getElementsByName (xecureFormName)[0].aSignedMsg.value = aResult;

    send_vid_info(fnSignDataWithVID);
}

// 공인인증서 종료 callback
function fnSignDataWithVID (aResult)
{

    var aResultVid = aResult;

    document.getElementsByName (xecureFormName)[0].aVidMsg.value = aResultVid;

    var frmLoginCert = document.getElementById(xecureFormName);

    frmLoginCert.submit();
}


// 공인인증서 종료 callback aResult 값만 넣어준다.
function SignDataCMS_confirm_callback (aResult)
{
    document.getElementsByName (xecureFormName)[0].aResult.value = aResult;
}

// 공인인증서 종료 callback aResult 값만 넣어준다.
function SignDataCMS_confirm_callback2 (aResult)
{
	document.getElementsByName (xecureFormName)[0].aResult.value = aResult;
	alert("인증 확인 되었습니다.");
}


function SignDataWithVID_confirm_callback(aResult)
{
	  document.getElementsByName (xecureFormName)[0].aSignedMsg.value = aResult;

    send_vid_info(fnSignDataWithVID_confirm);
}

function SignDataWithVID_confirm_callback_edu(aResult)
{
	  document.getElementsByName (xecureFormName)[0].aSignedMsg.value = aResult;

    send_vid_info(fnSignDataWithVID_confirm_edu);
}

function fnSignDataWithVID_confirm_edu (aResult)
{
    var aResultVid = aResult;

    document.getElementsByName (xecureFormName)[0].aVidMsg.value = aResultVid;
    
    fnCaEnd();
}

function fnSignDataWithVID_confirm (aResult)
{
    var aResultVid = aResult;

    document.getElementsByName (xecureFormName)[0].aVidMsg.value = aResultVid;
}


// 유효성 검사 시 사용한다. (로그인, 공인인증서 등록/수정)
function fnXecureLogin(){

    AnySign4PC_LoadCallback(_CB_fnXecureLogin);


    if(AnySign.mExtensionSetting.mInstallCheck_State != null && AnySign.mExtensionSetting.mInstallCheck_State != "ANYSIGN4PC_NORMAL")
    {
       PrintObjectTag();
    } else {
      _CB_fnXecureLogin();
    }
}

//유효성 검사 시 사용한다. (로그인, 공인인증서 등록/수정)
function fnXecureMobileLogin(){

    AnySign4PC_LoadCallback(_CB_fnXecureLogin);


    if(AnySign.mExtensionSetting.mInstallCheck_State != null && AnySign.mExtensionSetting.mInstallCheck_State != "ANYSIGN4PC_NORMAL")
    {
       PrintObjectTag();
    } else {
    	_CB_fnXecureMobileLogin();
    }
}

//fnXecureLogin Callback 함수(브라우저 인증서 우선 선택 시 4번째 파라미터를 null로 변경.)
function _CB_fnXecureMobileLogin(){

        AnySign.initSimpleSignCMS (AnySign.mXgateAddress,
                                          AnySign.mCAList,
                                          null,
                                          '16',
                                          'isarang',
                                          '10',
                                          '',
                                          AnySign.mLimitedTrial,
                                          SignDataCMS_callback);
}


// fnXecureLogin Callback 함수(브라우저 인증서 우선 선택 시 4번째 파라미터를 null로 변경.)
function _CB_fnXecureLogin(){

        AnySign.SignDataWithVID (AnySign.mXgateAddress,
                                          AnySign.mCAList,
                                          "isarang",
                                          '16',
                                          'isarang',
                                          '10',
                                          '',
                                          AnySign.mLimitedTrial,
                                          SignDataCMS_callback);
}

//유효성 검사 시 Submit을 안 할 시 사용한다.
function fnXecureConfirm(){
        AnySign.SignDataCMS (AnySign.mXgateAddress,
                                          AnySign.mCAList,
                                          'isarang',
                                          '10',
                                          '',
                                          AnySign.mLimitedTrial,
                                          SignDataCMS_confirm_callback);
}


//유효성 검사 시 Submit을 안 할 시 사용한다.(회원 가입)
function fnXecureConfirm2(){

        AnySign4PC_LoadCallback(_CB_fnXecureConfirm2);

        if(AnySign.mExtensionSetting.mInstallCheck_State != null && AnySign.mExtensionSetting.mInstallCheck_State != "ANYSIGN4PC_NORMAL")
        {
           PrintObjectTag();
        } else {
          _CB_fnXecureConfirm2();
        }


}

// fnXecureConfirm2 Callback 함수(브라우저 인증서 우선 선택 시 4번째 파라미터를 null로 변경.)
function _CB_fnXecureConfirm2(){

        AnySign.SignDataWithVID (AnySign.mXgateAddress,
                                          AnySign.mCAList,
                                          null,
                                          null,
                                          'isarang',
                                          '10',
                                          '',
                                          AnySign.mLimitedTrial,
                                          SignDataCMS_confirm_callback2);
}

function fnXecureVid(jumin){
	AnySign4PC_LoadCallback(_CB_fnXecureVid);

    if(AnySign.mExtensionSetting.mInstallCheck_State != null && AnySign.mExtensionSetting.mInstallCheck_State != "ANYSIGN4PC_NORMAL")
    {
       PrintObjectTag();
    } else {
    	_CB_fnXecureVid(jumin);
    }
}

function fnXecureVidMobile(jumin){
	AnySign4PC_LoadCallback(_CB_fnXecureVidMobile);

    if(AnySign.mExtensionSetting.mInstallCheck_State != null && AnySign.mExtensionSetting.mInstallCheck_State != "ANYSIGN4PC_NORMAL")
    {
       PrintObjectTag();
    } else {
    	_CB_fnXecureVidMobile(jumin);
    }
}

// 주민번호 검증할 시 사용한다.(브라우저 인증서 우선 선택 시 4번째 파라미터를 null로 변경.)
function _CB_fnXecureVid(jumin){
        AnySign.SignDataWithVID (AnySign.mXgateAddress,
                                          AnySign.mCAList,
                                          'isarang',
                                          '16',
                                          '',
                                          AnySign.mLimitedTrial,
                                          jumin,
                                          s,
                                          SignDataWithVID_callback);
}

//주민번호 검증할 시 사용한다.(브라우저 인증서 우선 선택 시 4번째 파라미터를 null로 변경.)
function _CB_fnXecureVidMobile(jumin){
        AnySign.initSimpleSignCMS (AnySign.mXgateAddress,
                                          AnySign.mCAList,
                                          'isarang',
                                          '16',
                                          '',
                                          AnySign.mLimitedTrial,
                                          jumin,
                                          s,
                                          SignDataWithVID_callback);
}


//주민번호 검증할 시 Submit을 안 할 시 사용한다.
function fnXecureVidConfirm(jumin){
		AnySign.SignDataWithVID (AnySign.mXgateAddress,
	            AnySign.mCAList,
	            'isarang',
	            '8',
	            '',
	            AnySign.mLimitedTrial,
	            jumin,
	            s,
	            SignDataWithVID_confirm_callback);
}

//주민번호 검증할 시 Submit을 안 할 시 사용한다.
function fnXecureVidConfirmEdu(jumin){
		AnySign.SignDataWithVID (AnySign.mXgateAddress,
	            AnySign.mCAList,
	            'isarang',
	            '8',
	            '',
	            AnySign.mLimitedTrial,
	            jumin,
	            s,
	            SignDataWithVID_confirm_callback_edu);
}





//------------------------------------------------------------ 팝업창 안의 팝업인증 -----------------------------------------------------------

function fnXecureValidPop(certJumin){
	var wWidth = 1100;
	var wHight = 780;

	var wX = (window.screen.width - wWidth) / 2;
	var wY = (window.screen.height - wHight) / 2;

	var openPop = window.open("about:blank", "xecureVidPop", "toolbar=yes,location=no,directories=no,status=no,menubar=no,scrollbars=yes,resizable=no,copyhistory=no,left="+wX+",top="+wY+",width="+wWidth+",height="+wHight);
	var frmLoginCert = document.getElementsByName (xecureFormName)[0];

	var inputTag = null;

	if( typeof(frmLoginCert.certJumin) == "undefined"){
		inputTag = document.createElement("input");
		inputTag.id = "certJumin";
		inputTag.type = "hidden";
		inputTag.value = certJumin;
		frmLoginCert.appendChild(inputTag);
	}else{
		inputTag = frmLoginCert.certJumin;
		inputTag.value = certJumin;
	}

	var backupURLinputTag = null;

	if( typeof(frmLoginCert.backupURL) == "undefined"){

		backupURLinputTag = document.createElement("input");
		backupURLinputTag.id = "backupURL";
		backupURLinputTag.type = "hidden";
		backupURLinputTag.value = frmLoginCert.action;
		frmLoginCert.appendChild(backupURLinputTag);

	}else{
		backupURLinputTag = frmLoginCert.backupURL;
		backupURLinputTag.value = frmLoginCert.action;
	}

	frmLoginCert.action = "/xecure/certValidFront.jsp";
	frmLoginCert.target = "xecureVidPop";
    frmLoginCert.submit();
}

function fnPopupXecureValid_callback (aResult)
{
  	var frmLoginCert = opener.document.getElementsByName(opener.xecureFormName)[0];

  	frmLoginCert.aSignedMsg.value = aResult;

    send_vid_info(fnXecureValid);
}

function fnXecureValid (aResult)
{
    var frmLoginCert = opener.document.getElementsByName(opener.xecureFormName)[0];
    var aResultVid = aResult;

    frmLoginCert.aVidMsg.value = aResultVid;

    frmLoginCert.action = frmLoginCert.backupURL.value;
    frmLoginCert.target = "_self";

    frmLoginCert.submit();
    window.close();
}


function fnPopupXecure_Errcallback (aResult)
{
	if(typeof xecard=="undefined"){
		alert(aResult.msg);
		window.close();
	}else{
		alert(aResult.msg+"\n\n※ 보육료 결제 중 인증서 오류가 발생한 경우, ARS 결제(☎1566-0244) 혹은 아이사랑 모바일 앱을 통해 결제 진행 부탁드립니다.\n서비스 이용에 불편을 드려 대단히 죄송합니다.");
		SimpleSign.onClose();
	}	
}


//인증서 인증하기(id, pass 찾기, 개명) 팝업 안에서 인증서 입력(브라우저 인증서 우선 선택 시 4번째 파라미터를 null로 변경.)
function fnPopupXecureVid(jumin){
    AnySign.SignDataWithVID (AnySign.mXgateAddress,
            AnySign.mCAList,
            'isarang',
            '16',
            '',
            AnySign.mLimitedTrial,
            jumin,
            s,
            SignDataWithVIDPopup_NoIdn_callback,
            fnPopupXecure_Errcallback);
    
}


//------------------------------------------------------------ 팝업창 안의 팝업인증 -----------------------------------------------------------


//보육료, 필요경비 결제
function fnVidNoIdnSettlePop(){
  var wWidth = 1100;
  var wHight = 780;

	var wX = (window.screen.width - wWidth) / 2;
	var wY = (window.screen.height - wHight) / 2;

	window.open("/xecure/certVidNoIdnSettleFront.jsp", "xecureVidPop", "toolbar=yes,location=no,directories=no,status=no,menubar=no,scrollbars=yes,resizable=no,copyhistory=no,left="+wX+",top="+wY+",width="+wWidth+",height="+wHight);

}

//비회원 결제 시 인증(브라우저 인증서 우선 선택 시 4번째 파라미터를 null로 변경.)
function fnXecurePopupVidNoIdnSettle(){
    
    AnySign.SignDataWithVID (AnySign.mXgateAddress,
            AnySign.mCAList,
            'isarang',
            '16',
            '',
            AnySign.mLimitedTrial,
            '',
            s,
            SignDataWithVIDPopup_NoIdn_callback,
            fnPopupXecure_Errcallback);

}


function SignDataWithVIDPopup_NoIdn_callback (aResult){
  vidResult = aResult;
  send_vid_info(fnSignDataWithVIDPopup_NoIdn);
}

function fnSignDataWithVIDPopup_NoIdn (aResult){
  var aResultVid = aResult;
  SignDataWithVID_NoIdn_callback(vidResult, aResultVid);
  window.close();
}

