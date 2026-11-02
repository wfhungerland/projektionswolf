' Bundesministerium für Wirtschaft und Klimaschutz
' Bundesministerium der Finanzen

' Programmcode zur Bestimmung des
' gesamtwirtschaftlichen Produktionspotenzials
' nach der Produktionsfunktionsmethode der EU
' im Rahmen der Frühjahrsprojektion der Bundesregierung
' vom 24. April 2025

' Zitierhinweis:
' Bundesministerium für Wirtschaft und Klimaschutz, Bundesministerium der Finanzen (2025): Frühjahrsprojektion der Bundesregierung vom 24. April 2025, Berlin.

' Voreinstellungen, Dateneinlese, Datenaufbereitung
%path = @runpath
cd %path
%einlese 	= "Input_EViews_FP25.xls"
%auslese 	= "Output_EViews_FP25.xlsx"

!starty 		= 1960
!endy_st		= 2026
!starty_mt	= !endy_st+1
!endy_mt	= 2029
!starty_f 		=  !endy_mt+1
!endy			= 2032

wfcreate(page="EViews_FP25") a !starty !endy

!elast_l 	= 0.65
!elast_k 	= 1-!elast_l

smpl @all
!q = 14
read(s=input_eviews, b3) %einlese !q
smpl @all

lur = lur/100
nairu = nairu/100
series lf = l / (1-lur)
series lf_fl = part_fl*popw_fl
smpl 2014 !endy_mt
series lf_nfl=lf-lf_fl
smpl !starty 2013
lf_nfl=lf
smpl @all
series part_nfl = 100*lf_nfl /popw_nfl
delete lf_nfl lf_fl lf
series totalh = l*hpere
smpl @all
series sr = log(y/(totalh^!elast_l*k^!elast_k))
smpl @all

' Potenzialschätzung

	' Partizipationsrate
smpl 1995 !endy_st
equation model_part_nfl.ls(optmethod=legacy) part_nfl part_nfl(-1) part_nfl(-2) 

smpl !starty_mt !endy
model_part_nfl.forecast(f=actual) part_f_nfl

smpl 1965 !endy
part_f_nfl.hpf(lambda=100) parts_nfl

smpl @all
part_nfl = part_f_nfl

series w_nfl= popw_nfl/(popw_nfl+popw_fl)
series w_fl=popw_fl/(popw_nfl+popw_fl)

smpl 2014 !endy_mt
series parts_w=w_nfl*parts_nfl+w_fl*(part_fl*100)

smpl !starty 2013
parts_w=parts_nfl

smpl 2014 !endy_mt
series part=w_nfl*part_f_nfl+w_fl*(part_fl*100)

smpl !starty 2013
part=part_f_nfl

smpl @all
series parts=parts_w
delete parts_w w_nfl w_fl parts_nfl part_f_nfl part_fl part_nfl

	' Arbeitszeit je ET
series hpere_mod = hpere
smpl 1976 !endy_st

series hpere_mod_aux = (hpere(-1)+hpere(+1))/2
smpl 2020 2020
hpere_mod = hpere_mod_aux
delete hpere_mod_aux
	
smpl 1976 !endy_st
equation model_hpere_mod.ls hpere_mod c hpere_mod(-1)

smpl !starty_mt !endy
model_hpere_mod.forecast(f=actual) hpere_mod_f

smpl 1965 !endy
hpere_mod_f.hpf(lambda=100) hperehp

smpl 1976 !endy_st
equation model_hpere.ls hpere c hpere(-1)

smpl !starty_mt !endy
model_hpere.forecast(f=actual) hpere_f

smpl @all
hpere= hpere_f
delete hpere_f hpere_mod_f  hpere_mod

	' Potenzielles Arbeitsvolumen
series totalhs = parts/100*popw*(1-nairu)*hperehp

	' Produktionspotenzial, Investitionsquote, Abgangsrate
smpl @all
series ypot = totalhs^!elast_l*k^!elast_k*exp(tfp)

series iypot = 100*iq / ypot

smpl 1995 !endy_st
equation model_iypot.ls iypot	 c iypot(-1) iypot(-2)

smpl !starty_mt !endy
model_iypot.forecast(f=actual) iypot_f

smpl @all
iypot= iypot_f
delete iypot_f

smpl @all
series dep = (iq - (k-k(-1)))/k(-1)
smpl !starty_mt !endy
dep = dep(-1)

smpl !starty_mt !endy_mt

model ypot_solve
ypot_solve.append @IDENTITY ypot  = (totalhs^!elast_l)  * (k^!elast_k)  * exp(tfp)
ypot_solve.append @IDENTITY k  = iq  + (1  - dep)  * k(-1)
ypot_solve.append @IDENTITY iq  = iypot/100  * ypot
ypot_solve.solve

smpl @all
iq = iq_0
k = k_0
delete ypot_0 iq_0 k_0 iypot

smpl !starty_mt !endy_mt
series iq_growth=(iq/iq(-3))^(1/3)
smpl !starty_mt !starty_mt
iq_growth=iq_growth(+2)
iq=iq(-1)*iq_growth
smpl !starty_mt+1 !starty_mt+1
iq_growth=iq_growth(+1)
iq=iq(-1)*iq_growth
delete iq_growth
smpl !starty_mt !endy_mt
k  = iq  + (1  - dep)  * k(-1)
sr = log(y/(totalh^!elast_l*k^!elast_k))

smpl @all
ypot  =  totalhs^!elast_l*k^!elast_k*exp(tfp)
delete totalh totalhs 
pagestruct(end=!endy_mt)

' Ergebnisaufbereitung
smpl @all

series ygap 			= (y/ypot-1)*100
series ypotn			= ypot* (yn/y)
dep						= 100* dep
nairu 						= 100* nairu
lur      					= 100* lur

pagesave(t=excelxml) %auslese


