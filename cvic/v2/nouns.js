// ═══════════════════════════════════════════════════════════════
// NOUNS.JS — Czech noun declension data (~200 nouns)
// Compact format: _(gender, pattern, type, 'sg forms', 'pl forms')
// sg/pl = nom,gen,dat,acc,voc,loc,ins
// type: p=person a=animal l=place f=food t=thing x=abstract b=body r=nature v=vehicle
// ═══════════════════════════════════════════════════════════════
const NOUNS={};
const _C=['nom','gen','dat','acc','voc','loc','ins'];
function _(g,p,tp,sg,pl){var s=sg.split(','),l=pl.split(','),o={gender:g,pattern:p,type:tp};for(var i=0;i<7;i++){o[_C[i]+'_sg']=s[i];o[_C[i]+'_pl']=l[i];}NOUNS[s[0]]=o;}

// ── MASCULINE ANIMATE — pán (hard) ──
_('ma','pán','p','student,studenta,studentovi,studenta,studente,studentovi,studentem','studenti,studentů,studentům,studenty,studenti,studentech,studenty');
_('ma','pán','p','bratr,bratra,bratrovi,bratra,bratře,bratrovi,bratrem','bratři,bratrů,bratrům,bratry,bratři,bratrech,bratry');
_('ma','pán','p','otec,otce,otci,otce,otče,otci,otcem','otcové,otců,otcům,otce,otcové,otcích,otci');
_('ma','pán','p','syn,syna,synovi,syna,synu,synovi,synem','synové,synů,synům,syny,synové,synech,syny');
_('ma','pán','p','soused,souseda,sousedovi,souseda,sousede,sousedovi,sousedem','sousedé,sousedů,sousedům,sousedy,sousedé,sousedech,sousedy');
_('ma','pán','p','lékař,lékaře,lékaři,lékaře,lékaři,lékaři,lékařem','lékaři,lékařů,lékařům,lékaře,lékaři,lékařích,lékaři');
_('ma','pán','p','kluk,kluka,klukovi,kluka,kluku,klukovi,klukem','kluci,kluků,klukům,kluky,kluci,klucích,kluky');
_('ma','pán','a','pes,psa,psovi,psa,pse,psovi,psem','psi,psů,psům,psy,psi,psech,psy');
_('ma','pán','p','kamarád,kamaráda,kamarádovi,kamaráda,kamaráde,kamarádovi,kamarádem','kamarádi,kamarádů,kamarádům,kamarády,kamarádi,kamarádech,kamarády');
_('ma','pán','p','pán,pána,pánovi,pána,pane,pánovi,pánem','páni,pánů,pánům,pány,páni,pánech,pány');
_('ma','pán','p','Čech,Čecha,Čechovi,Čecha,Čechu,Čechovi,Čechem','Češi,Čechů,Čechům,Čechy,Češi,Češích,Čechy');
_('ma','pán','p','manžel,manžela,manželovi,manžela,manželi,manželovi,manželem','manželé,manželů,manželům,manžely,manželé,manželech,manžely');
_('ma','pán','p','dědeček,dědečka,dědečkovi,dědečka,dědečku,dědečkovi,dědečkem','dědečkové,dědečků,dědečkům,dědečky,dědečkové,dědečcích,dědečky');
_('ma','pán','p','chlapec,chlapce,chlapci,chlapce,chlapče,chlapci,chlapcem','chlapci,chlapců,chlapcům,chlapce,chlapci,chlapcích,chlapci');
_('ma','pán','p','vnuk,vnuka,vnukovi,vnuka,vnuku,vnukovi,vnukem','vnuci,vnuků,vnukům,vnuky,vnuci,vnucích,vnuky');
_('ma','pán','p','voják,vojáka,vojákovi,vojáka,vojáku,vojákovi,vojákem','vojáci,vojáků,vojákům,vojáky,vojáci,vojácích,vojáky');
_('ma','pán','p','Němec,Němce,Němci,Němce,Němče,Němci,Němcem','Němci,Němců,Němcům,Němce,Němci,Němcích,Němci');
_('ma','pán','p','hoch,hocha,hochovi,hocha,hochu,hochovi,hochem','hoši,hochů,hochům,hochy,hoši,hoších,hochy');
_('ma','pán','p','doktor,doktora,doktorovi,doktora,doktore,doktorovi,doktorem','doktoři,doktorů,doktorům,doktory,doktoři,doktorech,doktory');
_('ma','pán','p','inženýr,inženýra,inženýrovi,inženýra,inženýre,inženýrovi,inženýrem','inženýři,inženýrů,inženýrům,inženýry,inženýři,inženýrech,inženýry');

// ── MASCULINE ANIMATE — muž (soft) ──
_('ma','muž','p','muž,muže,muži,muže,muži,muži,mužem','muži,mužů,mužům,muže,muži,mužích,muži');
_('ma','muž','p','učitel,učitele,učiteli,učitele,učiteli,učiteli,učitelem','učitelé,učitelů,učitelům,učitele,učitelé,učitelích,učiteli');
_('ma','muž','p','přítel,přítele,příteli,přítele,příteli,příteli,přítelem','přátelé,přátel,přátelům,přátele,přátelé,přátelích,přáteli');
_('ma','muž','p','prodavač,prodavače,prodavači,prodavače,prodavači,prodavači,prodavačem','prodavači,prodavačů,prodavačům,prodavače,prodavači,prodavačích,prodavači');
_('ma','muž','p','řidič,řidiče,řidiči,řidiče,řidiči,řidiči,řidičem','řidiči,řidičů,řidičům,řidiče,řidiči,řidičích,řidiči');
_('ma','muž','p','herec,herce,herci,herce,herče,herci,hercem','herci,herců,hercům,herce,herci,hercích,herci');
_('ma','muž','p','zpěvák,zpěváka,zpěvákovi,zpěváka,zpěváku,zpěvákovi,zpěvákem','zpěváci,zpěváků,zpěvákům,zpěváky,zpěváci,zpěvácích,zpěváky');
_('ma','muž','p','malíř,malíře,malíři,malíře,malíři,malíři,malířem','malíři,malířů,malířům,malíře,malíři,malířích,malíři');
_('ma','muž','p','tanečník,tanečníka,tanečníkovi,tanečníka,tanečníku,tanečníkovi,tanečníkem','tanečníci,tanečníků,tanečníkům,tanečníky,tanečníci,tanečnících,tanečníky');
_('ma','muž','p','sportovec,sportovce,sportovci,sportovce,sportovče,sportovci,sportovcem','sportovci,sportovců,sportovcům,sportovce,sportovci,sportovcích,sportovci');
_('ma','muž','p','vědec,vědce,vědci,vědce,vědče,vědci,vědcem','vědci,vědců,vědcům,vědce,vědci,vědcích,vědci');

// ── MASCULINE ANIMATE — předseda (-a) ──
_('ma','předseda','p','kolega,kolegy,kolegovi,kolegu,kolego,kolegovi,kolegou','kolegové,kolegů,kolegům,kolegy,kolegové,kolezích,kolegy');
_('ma','předseda','p','táta,táty,tátovi,tátu,táto,tátovi,tátou','tátové,tátů,tátům,táty,tátové,tátech,táty');
_('ma','předseda','p','starosta,starosty,starostovi,starostu,starosto,starostovi,starostou','starostové,starostů,starostům,starosty,starostové,starostech,starosty');
_('ma','předseda','p','turista,turisty,turistovi,turistu,turisto,turistovi,turistou','turisté,turistů,turistům,turisty,turisté,turistech,turisty');

// ── MASCULINE ANIMATE — irregular ──
_('ma','člověk','p','člověk,člověka,člověku,člověka,člověče,člověku,člověkem','lidé,lidí,lidem,lidi,lidé,lidech,lidmi');

// ── MASCULINE INANIMATE — hrad (hard) ──
_('mi','hrad','l','hrad,hradu,hradu,hrad,hrade,hradě,hradem','hrady,hradů,hradům,hrady,hrady,hradech,hrady');
_('mi','hrad','l','dům,domu,domu,dům,dome,domě,domem','domy,domů,domům,domy,domy,domech,domy');
_('mi','hrad','t','dopis,dopisu,dopisu,dopis,dopise,dopise,dopisem','dopisy,dopisů,dopisům,dopisy,dopisy,dopisech,dopisy');
_('mi','hrad','v','vlak,vlaku,vlaku,vlak,vlaku,vlaku,vlakem','vlaky,vlaků,vlakům,vlaky,vlaky,vlacích,vlaky');
_('mi','hrad','l','obchod,obchodu,obchodu,obchod,obchode,obchodě,obchodem','obchody,obchodů,obchodům,obchody,obchody,obchodech,obchody');
_('mi','hrad','f','oběd,oběda,obědu,oběd,oběde,obědě,obědem','obědy,obědů,obědům,obědy,obědy,obědech,obědy');
_('mi','hrad','t','stůl,stolu,stolu,stůl,stole,stole,stolem','stoly,stolů,stolům,stoly,stoly,stolech,stoly');
_('mi','hrad','r','les,lesa,lesu,les,lese,lese,lesem','lesy,lesů,lesům,lesy,lesy,lesích,lesy');
_('mi','hrad','l','most,mostu,mostu,most,moste,mostě,mostem','mosty,mostů,mostům,mosty,mosty,mostech,mosty');
_('mi','hrad','l','park,parku,parku,park,parku,parku,parkem','parky,parků,parkům,parky,parky,parcích,parky');
_('mi','hrad','l','hotel,hotelu,hotelu,hotel,hotele,hotelu,hotelem','hotely,hotelů,hotelům,hotely,hotely,hotelech,hotely');
_('mi','hrad','f','sýr,sýra,sýru,sýr,sýre,sýru,sýrem','sýry,sýrů,sýrům,sýry,sýry,sýrech,sýry');
_('mi','hrad','f','chléb,chleba,chlebu,chléb,chlebe,chlebě,chlebem','chleby,chlebů,chlebům,chleby,chleby,chlebech,chleby');
_('mi','hrad','l','byt,bytu,bytu,byt,byte,bytě,bytem','byty,bytů,bytům,byty,byty,bytech,byty');
_('mi','hrad','l','kostel,kostela,kostelu,kostel,kostele,kostele,kostelem','kostely,kostelů,kostelům,kostely,kostely,kostelech,kostely');
_('mi','hrad','f','čaj,čaje,čaji,čaj,čaji,čaji,čajem','čaje,čajů,čajům,čaje,čaje,čajích,čaji');
_('mi','hrad','t','svetr,svetru,svetru,svetr,svetře,svetru,svetrem','svetry,svetrů,svetrům,svetry,svetry,svetrech,svetry');
_('mi','hrad','t','kabát,kabátu,kabátu,kabát,kabáte,kabátě,kabátem','kabáty,kabátů,kabátům,kabáty,kabáty,kabátech,kabáty');
_('mi','hrad','x','rok,roku,roku,rok,roku,roce,rokem','roky,roků,rokům,roky,roky,rocích,roky');
_('mi','hrad','x','zákon,zákona,zákonu,zákon,zákone,zákoně,zákonem','zákony,zákonů,zákonům,zákony,zákony,zákonech,zákony');
_('mi','hrad','x','problém,problému,problému,problém,probléme,problému,problémem','problémy,problémů,problémům,problémy,problémy,problémech,problémy');
_('mi','hrad','r','vítr,větru,větru,vítr,větře,větru,větrem','větry,větrů,větrům,větry,větry,větrech,větry');
_('mi','hrad','r','kopec,kopce,kopci,kopec,kopce,kopci,kopcem','kopce,kopců,kopcům,kopce,kopce,kopcích,kopci');
_('mi','hrad','r','strom,stromu,stromu,strom,strome,stromě,stromem','stromy,stromů,stromům,stromy,stromy,stromech,stromy');
_('mi','hrad','r','kámen,kamene,kameni,kámen,kameni,kameni,kamenem','kameny,kamenů,kamenům,kameny,kameny,kamenech,kameny');
_('mi','hrad','r','potok,potoka,potoku,potok,potoku,potoce,potokem','potoky,potoků,potokům,potoky,potoky,potocích,potoky');
_('mi','hrad','t','obraz,obrazu,obrazu,obraz,obraze,obraze,obrazem','obrazy,obrazů,obrazům,obrazy,obrazy,obrazech,obrazy');
_('mi','hrad','t','telefon,telefonu,telefonu,telefon,telefone,telefonu,telefonem','telefony,telefonů,telefonům,telefony,telefony,telefonech,telefony');
_('mi','hrad','t','počítač,počítače,počítači,počítač,počítači,počítači,počítačem','počítače,počítačů,počítačům,počítače,počítače,počítačích,počítači');
_('mi','hrad','x','čas,času,času,čas,čase,čase,časem','časy,časů,časům,časy,časy,časech,časy');
_('mi','hrad','x','měsíc,měsíce,měsíci,měsíc,měsíci,měsíci,měsícem','měsíce,měsíců,měsícům,měsíce,měsíce,měsících,měsíci');
_('mi','hrad','x','svět,světa,světu,svět,světe,světě,světem','světy,světů,světům,světy,světy,světech,světy');
_('mi','hrad','x','jazyk,jazyka,jazyku,jazyk,jazyku,jazyce,jazykem','jazyky,jazyků,jazykům,jazyky,jazyky,jazycích,jazyky');
_('mi','hrad','t','film,filmu,filmu,film,filme,filmu,filmem','filmy,filmů,filmům,filmy,filmy,filmech,filmy');
_('mi','hrad','x','život,života,životu,život,živote,životě,životem','životy,životů,životům,životy,životy,životech,životy');
_('mi','hrad','r','vzduch,vzduchu,vzduchu,vzduch,vzduchu,vzduchu,vzduchem','vzduchy,vzduchů,vzduchům,vzduchy,vzduchy,vzduchách,vzduchy');
_('mi','hrad','l','zámek,zámku,zámku,zámek,zámku,zámku,zámkem','zámky,zámků,zámkům,zámky,zámky,zámcích,zámky');
_('mi','hrad','r','rybník,rybníka,rybníku,rybník,rybníku,rybníce,rybníkem','rybníky,rybníků,rybníkům,rybníky,rybníky,rybnících,rybníky');
_('mi','hrad','r','sníh,sněhu,sněhu,sníh,sněhu,sněhu,sněhem','sněhy,sněhů,sněhům,sněhy,sněhy,snězích,sněhy');
_('mi','hrad','r','déšť,deště,dešti,déšť,dešti,dešti,deštěm','deště,dešťů,dešťům,deště,deště,deštích,dešti');
_('mi','hrad','l','pivovar,pivovaru,pivovaru,pivovar,pivovare,pivovaře,pivovarem','pivovary,pivovarů,pivovarům,pivovary,pivovary,pivovarech,pivovary');
_('mi','hrad','t','koberec,koberce,koberci,koberec,koberče,koberci,kobercem','koberce,koberců,kobercům,koberce,koberce,kobercích,koberci');
_('mi','hrad','r','dub,dubu,dubu,dub,dube,dubu,dubem','duby,dubů,dubům,duby,duby,dubech,duby');
_('mi','hrad','v','autobus,autobusu,autobusu,autobus,autobuse,autobusu,autobusem','autobusy,autobusů,autobusům,autobusy,autobusy,autobusech,autobusy');
_('mi','hrad','l','chrám,chrámu,chrámu,chrám,chráme,chrámě,chrámem','chrámy,chrámů,chrámům,chrámy,chrámy,chrámech,chrámy');
_('mi','hrad','x','dar,daru,daru,dar,dare,daru,darem','dary,darů,darům,dary,dary,darech,dary');
_('mi','hrad','x','cíl,cíle,cíli,cíl,cíli,cíli,cílem','cíle,cílů,cílům,cíle,cíle,cílech,cíli');

// ── MASCULINE INANIMATE — stroj (soft) ──
_('mi','stroj','t','stroj,stroje,stroji,stroj,stroji,stroji,strojem','stroje,strojů,strojům,stroje,stroje,strojích,stroji');
_('mi','stroj','l','pokoj,pokoje,pokoji,pokoj,pokoji,pokoji,pokojem','pokoje,pokojů,pokojům,pokoje,pokoje,pokojích,pokoji');
_('mi','stroj','t','klíč,klíče,klíči,klíč,klíči,klíči,klíčem','klíče,klíčů,klíčům,klíče,klíče,klíčích,klíči');
_('mi','stroj','t','nůž,nože,noži,nůž,noži,noži,nožem','nože,nožů,nožům,nože,nože,nožích,noži');
_('mi','stroj','t','míč,míče,míči,míč,míči,míči,míčem','míče,míčů,míčům,míče,míče,míčích,míči');
_('mi','stroj','l','kraj,kraje,kraji,kraj,kraji,kraji,krajem','kraje,krajů,krajům,kraje,kraje,krajích,kraji');
_('mi','stroj','t','koš,koše,koši,koš,koši,koši,košem','koše,košů,košům,koše,koše,koších,koši');
_('mi','stroj','r','oheň,ohně,ohni,oheň,ohni,ohni,ohněm','ohně,ohňů,ohňům,ohně,ohně,ohních,ohni');

// ── MASCULINE INANIMATE — irregular ──
_('mi','den','x','den,dne,dni,den,dni,dni,dnem','dny,dnů,dnům,dny,dny,dnech,dny');
_('mi','týden','x','týden,týdne,týdnu,týden,týdne,týdnu,týdnem','týdny,týdnů,týdnům,týdny,týdny,týdnech,týdny');

// ── FEMININE — žena (hard -a) ──
_('f','žena','p','žena,ženy,ženě,ženu,ženo,ženě,ženou','ženy,žen,ženám,ženy,ženy,ženách,ženami');
_('f','žena','t','kniha,knihy,knize,knihu,kniho,knize,knihou','knihy,knih,knihám,knihy,knihy,knihách,knihami');
_('f','žena','l','škola,školy,škole,školu,školo,škole,školou','školy,škol,školám,školy,školy,školách,školami');
_('f','žena','p','sestra,sestry,sestře,sestru,sestro,sestře,sestrou','sestry,sester,sestrám,sestry,sestry,sestrách,sestrami');
_('f','žena','l','zahrada,zahrady,zahradě,zahradu,zahrado,zahradě,zahradou','zahrady,zahrad,zahradám,zahrady,zahrady,zahradách,zahradami');
_('f','žena','f','voda,vody,vodě,vodu,vodo,vodě,vodou','vody,vod,vodám,vody,vody,vodách,vodami');
_('f','žena','p','dcera,dcery,dceři,dceru,dcero,dceři,dcerou','dcery,dcer,dcerám,dcery,dcery,dcerách,dcerami');
_('f','žena','f','káva,kávy,kávě,kávu,kávo,kávě,kávou','kávy,káv,kávám,kávy,kávy,kávách,kávami');
_('f','žena','f','polévka,polévky,polévce,polévku,polévko,polévce,polévkou','polévky,polévek,polévkám,polévky,polévky,polévkách,polévkami');
_('f','žena','r','cesta,cesty,cestě,cestu,cesto,cestě,cestou','cesty,cest,cestám,cesty,cesty,cestách,cestami');
_('f','žena','p','matka,matky,matce,matku,matko,matce,matkou','matky,matek,matkám,matky,matky,matkách,matkami');
_('f','žena','t','taška,tašky,tašce,tašku,taško,tašce,taškou','tašky,tašek,taškám,tašky,tašky,taškách,taškami');
_('f','žena','t','bota,boty,botě,botu,boto,botě,botou','boty,bot,botám,boty,boty,botách,botami');
_('f','žena','b','noha,nohy,noze,nohu,noho,noze,nohou','nohy,noh,nohám,nohy,nohy,nohách,nohami');
_('f','žena','b','hlava,hlavy,hlavě,hlavu,hlavo,hlavě,hlavou','hlavy,hlav,hlavám,hlavy,hlavy,hlavách,hlavami');
_('f','žena','b','ruka,ruky,ruce,ruku,ruko,ruce,rukou','ruce,rukou,rukám,ruce,ruce,rukách,rukama');
_('f','žena','l','lékárna,lékárny,lékárně,lékárnu,lékárno,lékárně,lékárnou','lékárny,lékáren,lékárnám,lékárny,lékárny,lékárnách,lékárnami');
_('f','žena','l','zastávka,zastávky,zastávce,zastávku,zastávko,zastávce,zastávkou','zastávky,zastávek,zastávkám,zastávky,zastávky,zastávkách,zastávkami');
_('f','žena','l','pošta,pošty,poště,poštu,pošto,poště,poštou','pošty,pošt,poštám,pošty,pošty,poštách,poštami');
_('f','žena','r','hora,hory,hoře,horu,horo,hoře,horou','hory,hor,horám,hory,hory,horách,horami');
_('f','žena','r','řeka,řeky,řece,řeku,řeko,řece,řekou','řeky,řek,řekám,řeky,řeky,řekách,řekami');
_('f','žena','r','skála,skály,skále,skálu,skálo,skále,skálou','skály,skál,skálám,skály,skály,skálách,skálami');
_('f','žena','r','květina,květiny,květině,květinu,květino,květině,květinou','květiny,květin,květinám,květiny,květiny,květinách,květinami');
_('f','žena','t','mapa,mapy,mapě,mapu,mapo,mapě,mapou','mapy,map,mapám,mapy,mapy,mapách,mapami');
_('f','žena','r','půda,půdy,půdě,půdu,půdo,půdě,půdou','půdy,půd,půdám,půdy,půdy,půdách,půdami');
_('f','žena','l','lavička,lavičky,lavičce,lavičku,lavičko,lavičce,lavičkou','lavičky,laviček,lavičkám,lavičky,lavičky,lavičkách,lavičkami');
_('f','žena','l','hospoda,hospody,hospodě,hospodu,hospodo,hospodě,hospodou','hospody,hospod,hospodám,hospody,hospody,hospodách,hospodami');
_('f','žena','l','brána,brány,bráně,bránu,bráno,bráně,bránou','brány,bran,bránám,brány,brány,bránách,bránami');
_('f','žena','t','koruna,koruny,koruně,korunu,koruno,koruně,korunou','koruny,korun,korunám,koruny,koruny,korunách,korunami');
_('f','žena','x','hodina,hodiny,hodině,hodinu,hodino,hodině,hodinou','hodiny,hodin,hodinám,hodiny,hodiny,hodinách,hodinami');
_('f','žena','x','minuta,minuty,minutě,minutu,minuto,minutě,minutou','minuty,minut,minutám,minuty,minuty,minutách,minutami');
_('f','žena','x','strana,strany,straně,stranu,strano,straně,stranou','strany,stran,stranám,strany,strany,stranách,stranami');
_('f','žena','x','barva,barvy,barvě,barvu,barvo,barvě,barvou','barvy,barev,barvám,barvy,barvy,barvách,barvami');
_('f','žena','a','kočka,kočky,kočce,kočku,kočko,kočce,kočkou','kočky,koček,kočkám,kočky,kočky,kočkách,kočkami');
_('f','žena','a','ryba,ryby,rybě,rybu,rybo,rybě,rybou','ryby,ryb,rybám,ryby,ryby,rybách,rybami');
_('f','žena','r','tráva,trávy,trávě,trávu,trávo,trávě,trávou','trávy,tráv,trávám,trávy,trávy,trávách,trávami');
_('f','žena','t','lampa,lampy,lampě,lampu,lampo,lampě,lampou','lampy,lamp,lampám,lampy,lampy,lampách,lampami');
_('f','žena','r','hvězda,hvězdy,hvězdě,hvězdu,hvězdo,hvězdě,hvězdou','hvězdy,hvězd,hvězdám,hvězdy,hvězdy,hvězdách,hvězdami');
_('f','žena','l','továrna,továrny,továrně,továrnu,továrno,továrně,továrnou','továrny,továren,továrnám,továrny,továrny,továrnách,továrnami');
_('f','žena','l','nemocnice,nemocnice,nemocnici,nemocnici,nemocnice,nemocnici,nemocnicí','nemocnice,nemocnic,nemocnicím,nemocnice,nemocnice,nemocnicích,nemocnicemi');

// ── FEMININE — růže (soft -e) ──
_('f','růže','x','práce,práce,práci,práci,práce,práci,prací','práce,prací,pracím,práce,práce,pracích,pracemi');
_('f','růže','l','restaurace,restaurace,restauraci,restauraci,restaurace,restauraci,restaurací','restaurace,restaurací,restauracím,restaurace,restaurace,restauracích,restauracemi');
_('f','růže','t','košile,košile,košili,košili,košile,košili,košilí','košile,košil,košilím,košile,košile,košilích,košilemi');
_('f','růže','l','ulice,ulice,ulici,ulici,ulice,ulici,ulicí','ulice,ulic,ulicím,ulice,ulice,ulicích,ulicemi');
_('f','růže','r','růže,růže,růži,růži,růže,růži,růží','růže,růží,růžím,růže,růže,růžích,růžemi');
_('f','růže','l','galerie,galerie,galerii,galerii,galerie,galerii,galerií','galerie,galerií,galeriím,galerie,galerie,galeriích,galeriemi');
_('f','růže','x','tradice,tradice,tradici,tradici,tradice,tradici,tradicí','tradice,tradic,tradicím,tradice,tradice,tradicích,tradicemi');
_('f','růže','l','stanice,stanice,stanici,stanici,stanice,stanici,stanicí','stanice,stanic,stanicím,stanice,stanice,stanicích,stanicemi');
_('f','růže','r','vinice,vinice,vinici,vinici,vinice,vinici,vinicí','vinice,vinic,vinicím,vinice,vinice,vinicích,vinicemi');
_('f','růže','x','lekce,lekce,lekci,lekci,lekce,lekci,lekcí','lekce,lekcí,lekcím,lekce,lekce,lekcích,lekcemi');

// ── FEMININE — píseň (soft -Ø) ──
_('f','píseň','t','píseň,písně,písni,píseň,písni,písni,písní','písně,písní,písním,písně,písně,písních,písněmi');
_('f','píseň','l','kancelář,kanceláře,kanceláři,kancelář,kanceláři,kanceláři,kanceláří','kanceláře,kanceláří,kancelářím,kanceláře,kanceláře,kancelářích,kancelářemi');
_('f','píseň','v','tramvaj,tramvaje,tramvaji,tramvaj,tramvaji,tramvaji,tramvají','tramvaje,tramvají,tramvajím,tramvaje,tramvaje,tramvajích,tramvajemi');
_('f','píseň','r','jabloň,jabloně,jabloni,jabloň,jabloni,jabloni,jabloní','jabloně,jabloní,jabloním,jabloně,jabloně,jabloních,jabloněmi');
_('f','píseň','x','báseň,básně,básni,báseň,básni,básni,básní','básně,básní,básním,básně,básně,básních,básněmi');
_('f','píseň','x','odpověď,odpovědi,odpovědi,odpověď,odpovědi,odpovědi,odpovědí','odpovědi,odpovědí,odpovědím,odpovědi,odpovědi,odpovědích,odpověďmi');
_('f','píseň','t','postel,postele,posteli,postel,posteli,posteli,postelí','postele,postelí,postelím,postele,postele,postelích,postelemi');

// ── FEMININE — kost (-Ø) ──
_('f','kost','t','věc,věci,věci,věc,věci,věci,věcí','věci,věcí,věcem,věci,věci,věcech,věcmi');
_('f','kost','x','noc,noci,noci,noc,noci,noci,nocí','noci,nocí,nocím,noci,noci,nocích,nocemi');
_('f','kost','t','zeď,zdi,zdi,zeď,zdi,zdi,zdí','zdi,zdí,zdem,zdi,zdi,zdech,zdmi');
_('f','kost','b','kost,kosti,kosti,kost,kosti,kosti,kostí','kosti,kostí,kostem,kosti,kosti,kostech,kostmi');
_('f','kost','f','sůl,soli,soli,sůl,soli,soli,solí','soli,solí,solím,soli,soli,solích,solemi');
_('f','kost','x','moc,moci,moci,moc,moci,moci,mocí','moci,mocí,mocem,moci,moci,mocech,mocmi');
_('f','kost','a','myš,myši,myši,myš,myši,myši,myší','myši,myší,myším,myši,myši,myších,myšmi');
_('f','kost','x','řeč,řeči,řeči,řeč,řeči,řeči,řečí','řeči,řečí,řečem,řeči,řeči,řečech,řečmi');
_('f','kost','x','paměť,paměti,paměti,paměť,paměti,paměti,pamětí','paměti,pamětí,pamětem,paměti,paměti,pamětech,pamětmi');
_('f','kost','r','věž,věže,věži,věž,věži,věži,věží','věže,věží,věžím,věže,věže,věžích,věžemi');

// ── NEUTER — město (hard -o) ──
_('n','město','l','město,města,městu,město,město,městě,městem','města,měst,městům,města,města,městech,městy');
_('n','město','v','auto,auta,autu,auto,auto,autě,autem','auta,aut,autům,auta,auta,autech,auty');
_('n','město','t','okno,okna,oknu,okno,okno,okně,oknem','okna,oken,oknům,okna,okna,oknech,okny');
_('n','město','x','slovo,slova,slovu,slovo,slovo,slově,slovem','slova,slov,slovům,slova,slova,slovech,slovy');
_('n','město','f','pivo,piva,pivu,pivo,pivo,pivu,pivem','piva,piv,pivům,piva,piva,pivech,pivy');
_('n','město','f','jídlo,jídla,jídlu,jídlo,jídlo,jídle,jídlem','jídla,jídel,jídlům,jídla,jídla,jídlech,jídly');
_('n','město','f','maso,masa,masu,maso,maso,mase,masem','masa,mas,masům,masa,masa,masech,masy');
_('n','město','f','víno,vína,vínu,víno,víno,víně,vínem','vína,vín,vínům,vína,vína,vínech,víny');
_('n','město','l','divadlo,divadla,divadlu,divadlo,divadlo,divadle,divadlem','divadla,divadel,divadlům,divadla,divadla,divadlech,divadly');
_('n','město','v','kolo,kola,kolu,kolo,kolo,kole,kolem','kola,kol,kolům,kola,kola,kolech,koly');
_('n','město','l','středisko,střediska,středisku,středisko,středisko,středisku,střediskem','střediska,středisek,střediskům,střediska,střediska,střediscích,středisky');
_('n','město','x','jméno,jména,jménu,jméno,jméno,jméně,jménem','jména,jmen,jménům,jména,jména,jménech,jmény');
_('n','město','l','místo,místa,místu,místo,místo,místě,místem','místa,míst,místům,místa,místa,místech,místy');
_('n','město','t','křeslo,křesla,křeslu,křeslo,křeslo,křesle,křeslem','křesla,křesel,křeslům,křesla,křesla,křeslech,křesly');
_('n','město','f','máslo,másla,máslu,máslo,máslo,másle,máslem','másla,másel,máslům,másla,másla,máslech,másly');
_('n','město','b','koleno,kolena,kolenu,koleno,koleno,koleni,kolenem','kolena,kolen,kolenům,kolena,kolena,kolenech,koleny');
_('n','město','x','jaro,jara,jaru,jaro,jaro,jaře,jarem','jara,jar,jarům,jara,jara,jarech,jary');
_('n','město','x','léto,léta,létu,léto,léto,létě,létem','léta,let,létům,léta,léta,létech,léty');
_('n','město','x','ráno,rána,ránu,ráno,ráno,ránu,ránem','rána,rán,ránům,rána,rána,ránech,rány');
_('n','město','x','právo,práva,právu,právo,právo,právu,právem','práva,práv,právům,práva,práva,právech,právy');
_('n','město','x','číslo,čísla,číslu,číslo,číslo,čísle,číslem','čísla,čísel,číslům,čísla,čísla,číslech,čísly');
_('n','město','l','kino,kina,kinu,kino,kino,kině,kinem','kina,kin,kinům,kina,kina,kinech,kiny');
_('n','město','t','pero,pera,peru,pero,pero,peru,perem','pera,per,perům,pera,pera,perech,pery');
_('n','město','l','muzeum,muzea,muzeu,muzeum,muzeum,muzeu,muzeem','muzea,muzeí,muzeím,muzea,muzea,muzeích,muzei');
_('n','město','t','lano,lana,lanu,lano,lano,laně,lanem','lana,lan,lanům,lana,lana,lanech,lany');

// ── NEUTER — moře (soft -e) ──
_('n','moře','r','moře,moře,moři,moře,moře,moři,mořem','moře,moří,mořím,moře,moře,mořích,moři');
_('n','moře','b','srdce,srdce,srdci,srdce,srdce,srdci,srdcem','srdce,srdcí,srdcím,srdce,srdce,srdcích,srdci');
_('n','moře','l','letiště,letiště,letišti,letiště,letiště,letišti,letištěm','letiště,letišť,letištím,letiště,letiště,letištích,letišti');
_('n','moře','f','ovoce,ovoce,ovoci,ovoce,ovoce,ovoci,ovocem','ovoce,ovoce,ovoce,ovoce,ovoce,ovoce,ovoce');
_('n','moře','r','pole,pole,poli,pole,pole,poli,polem','pole,polí,polím,pole,pole,polích,poli');
_('n','moře','r','slunce,slunce,slunci,slunce,slunce,slunci,sluncem','slunce,sluncí,sluncím,slunce,slunce,sluncích,slunci');
_('n','moře','l','pracoviště,pracoviště,pracovišti,pracoviště,pracoviště,pracovišti,pracovištěm','pracoviště,pracovišť,pracovištím,pracoviště,pracoviště,pracovištích,pracovišti');

// ── NEUTER — stavení (-í) ──
_('n','stavení','l','nádraží,nádraží,nádraží,nádraží,nádraží,nádraží,nádražím','nádraží,nádraží,nádražím,nádraží,nádraží,nádražích,nádražími');
_('n','stavení','l','náměstí,náměstí,náměstí,náměstí,náměstí,náměstí,náměstím','náměstí,náměstí,náměstím,náměstí,náměstí,náměstích,náměstími');
_('n','stavení','x','počasí,počasí,počasí,počasí,počasí,počasí,počasím','počasí,počasí,počasím,počasí,počasí,počasích,počasími');
_('n','stavení','x','cvičení,cvičení,cvičení,cvičení,cvičení,cvičení,cvičením','cvičení,cvičení,cvičením,cvičení,cvičení,cvičeních,cvičeními');
_('n','stavení','r','údolí,údolí,údolí,údolí,údolí,údolí,údolím','údolí,údolí,údolím,údolí,údolí,údolích,údolími');
_('n','stavení','l','poschodí,poschodí,poschodí,poschodí,poschodí,poschodí,poschodím','poschodí,poschodí,poschodím,poschodí,poschodí,poschodích,poschodími');
_('n','stavení','r','pohoří,pohoří,pohoří,pohoří,pohoří,pohoří,pohořím','pohoří,pohoří,pohořím,pohoří,pohoří,pohořích,pohořími');
_('n','stavení','x','prostředí,prostředí,prostředí,prostředí,prostředí,prostředí,prostředím','prostředí,prostředí,prostředím,prostředí,prostředí,prostředích,prostředími');

// ── NEUTER — kuře (-e/-ete) ──
_('n','kuře','a','kuře,kuřete,kuřeti,kuře,kuře,kuřeti,kuřetem','kuřata,kuřat,kuřatům,kuřata,kuřata,kuřatech,kuřaty');
_('n','kuře','a','děvče,děvčete,děvčeti,děvče,děvče,děvčeti,děvčetem','děvčata,děvčat,děvčatům,děvčata,děvčata,děvčatech,děvčaty');
_('n','kuře','a','zvíře,zvířete,zvířeti,zvíře,zvíře,zvířeti,zvířetem','zvířata,zvířat,zvířatům,zvířata,zvířata,zvířatech,zvířaty');

// ── NEUTER — irregular ──
_('n','dítě','p','dítě,dítěte,dítěti,dítě,dítě,dítěti,dítětem','děti,dětí,dětem,děti,děti,dětech,dětmi');
_('n','oko','b','oko,oka,oku,oko,oko,oku,okem','oči,očí,očím,oči,oči,očích,očima');
_('n','ucho','b','ucho,ucha,uchu,ucho,ucho,uchu,uchem','uši,uší,uším,uši,uši,uších,ušima');
