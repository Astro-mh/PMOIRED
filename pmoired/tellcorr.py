#  correct tellurics for GRAVITY spectra
import numpy as np
import matplotlib.pyplot as plt
from astropy.io import fits
import scipy.interpolate
import sys, os
import time

try:
    import pmoired.dpfit as dpfit
except:
    import dpfit

this_dir, this_filename = os.path.split(__file__)

wv1 = '020' # 2mm Water Vapor
f = fits.open(os.path.join(this_dir, 'transnir'+wv1+'.fits'))
lbda = f[1].data['WAVELENGTH'][0].copy()
tran = f[1].data['TRANSMISSION'][0].copy()
f.close()
tran = tran[(lbda<2.45)*(lbda>1.95)]
lbda = lbda[(lbda<2.45)*(lbda>1.95)]
tran20, lbda = 1.0*tran[::50], lbda[::50]
f = fits.open(os.path.join(this_dir, 'emisnir'+wv1+'.fits'))
lbda0 = f[1].data['WAVELENGTH'][0].copy()
tran0 = f[1].data['EMISSION'][0].copy()
tran20 += np.interp(lbda, lbda0[::50], tran0[::50])
f.close()

wv2 = '080' # 8mm Water Vapor
f = fits.open(os.path.join(this_dir, 'transnir'+wv2+'.fits'))
lbda = f[1].data['WAVELENGTH'][0].copy()
tran = f[1].data['TRANSMISSION'][0].copy()
f.close()
tran = tran[(lbda<2.45)*(lbda>1.95)]
lbda = lbda[(lbda<2.45)*(lbda>1.95)]
tran80, lbda = 1.0*tran[::50], lbda[::50]
f = fits.open(os.path.join(this_dir, 'emisnir'+wv2+'.fits'))
lbda0 = f[1].data['WAVELENGTH'][0].copy()
tran0 = f[1].data['EMISSION'][0].copy()
tran80 += np.interp(lbda, lbda0[::50], tran0[::50])
f.close()

def Ftran(l, param, retWL=False):
    """
    'dl0', 'wl0', 'dl1',

    wl -> (wl-dl0)
    wl -> dli*(wl-wl0)**i + wl0
    """
    global tran20, tran80, lbda, t80_20

    tmpL = 1.0*lbda

    # -- wavelengt correction
    if 'dl0' in param.keys():
        tmpL -= param['dl0']
    if 'dl1' in param.keys() and 'wl0' in param.keys():
        tmpL = param['dl1']*(tmpL-param['wl0']) + param['wl0']

    for i in [2,3,4,5,6,7,8,9,10]:
        if 'dl'+str(i) in param.keys() and 'wl0' in param.keys():
            tmpL += param['dl'+str(i)]*(tmpL-param['wl0'])**i

    if retWL:
        return np.interp(l, tmpL, lbda)

    if 'pwv' in param.keys():
        tmpT = tran20 + (param['pwv']-2.0)*(tran80-tran20)/6.0
    else:
        tmpT = tran80

    if 'pow' in param.keys():
        tmpT = 1-np.abs(1-tmpT)**param['pow']


    # -- local corrections
    pc = filter(lambda x: x.startswith('p_'), param.keys())
    for x in pc:
        #
        wl0 = float(x.split('_')[1])
        if 'kern' in param:
            dwl = 1.5*param['kern']
        elif 'kern_min' in param and 'kern_max' in param:
            dwl = 0.75*(param['kern_min']+param['kern_max'])
        w = np.abs(tmpL-wl0)<dwl
        tmpT[w] = 1-(1-tmpT[w])**param[x]

    if 'kern' in param.keys():
        if 'kernp' in param.keys():
            kp = param['kernp']
        else:
            kp = 2.0
        kern = np.exp(-np.abs((tmpL-np.mean(tmpL))/param['kern'])**kp)
        kern /= np.sum(kern)
        tmpT = np.convolve(tmpT, kern, 'same')

    if 'kern_min' in param.keys() and 'kern_max' in param.keys():
        if 'kernp_min' in param.keys():
            kp_min = param['kernp_min']
        else:
            kp_min = 2.0
        if 'kernp_max' in param.keys():
            kp_max = param['kernp_max']
        else:
            kp_max = 2.0
        kern_min = np.exp(-np.abs((tmpL-np.mean(tmpL))/param['kern_min'])**kp_min)
        kern_max = np.exp(-np.abs((tmpL-np.mean(tmpL))/param['kern_max'])**kp_max)
        kern_min /= np.sum(kern_min)
        kern_max /= np.sum(kern_max)
        c = np.minimum(np.maximum((tmpL-np.min(l))/(np.ptp(l)), 0), 1)
        tmpT = (1-c)*np.convolve(tmpT, kern_min, 'same') + c*np.convolve(tmpT, kern_max, 'same')

    # -- spline shape
    X = sorted(filter(lambda x: x.startswith('xS'), param.keys()))
    Y = sorted(filter(lambda x: x.startswith('yS'), param.keys()))
    if len(X)==len(Y) and len(X):
        tmpT *= scipy.interpolate.interp1d([param[x] for x in X], [param[y] for y in Y], kind='cubic', fill_value='extrapolate')(tmpL)
    return np.interp(l, tmpL, tmpT)


def gravity(filename, quiet=True, save=True, wlmin=None, wlmax=None, avoid=None,
            fig=None, force=False):
    """
    avoid: list of tuple of wlmin, wlmax to avoid in the fit (known) line
    """
    # -- LOAD DATA -------------------------------------------------
    f = fits.open(filename)

    # -- check if telluric already computed
    alreadyComputed = False
    for h in f:
        if 'EXTNAME' in h.header and h.header['EXTNAME']=='TELLURICS':
            alreadyComputed = True
    if not force and alreadyComputed:
        print('tellurics already computed for %s'%filename, end=' ')
        print('use "force=True" to recompute')
        f.close()
        return

    if 'MED' in f[0].header['ESO INS SPEC RES']:
        MR = True
    elif 'HIGH' in f[0].header['ESO INS SPEC RES']:
        MR = False
    else:
        print('Nothing to do for resolution', f[0].header['ESO INS SPEC RES'])
        return

    # -- init plot ----------------------------------------
    if not fig is None:
        quiet = False
    if not quiet:
        if fig is None:
            fig = 1
        plt.close(fig)
        plt.figure(fig, figsize=(10,5))
        plt.clf()
        plt.subplots_adjust(right=0.99, left=0.05)

    # -- HARDWIRED, DANGEROUS!!! -> works for POLA and JOINED
    wl = f[4].data['EFF_WAVE']*1e6
    if len(wl)<10:
        wl = f[3].data['EFF_WAVE']*1e6

    if not quiet:
        print('WL (all):', wl.shape)

    # -- fitting domain:
    if wlmin is None:
        wlmin = 1.9
    if wlmax is None:
        wlmax = 2.5

    pola = f[0].header['HIERARCH ESO FT POLA MODE'].strip()=='SPLIT'

    # -- sum of fluxes, remove outliers -----------------------------
    sp, n = 0.0, 3
    fl = None
    for i in range(4):
        if pola:
            _sp = f[18].data['FLUX'][i,:]+f[22].data['FLUX'][i,:]
            _fl = np.logical_or(f[18].data['FLAG'][i,:], f[22].data['FLAG'][i,:])
        else:
            _sp = f[12].data['FLUX'][i,:].copy()
            _fl = f[12].data['FLAG'][i,:].copy()
        sp += _sp
        if fl is None:
            fl = _fl
        else:
            fl = np.logical_or(fl, _fl)
    # -- close FITS file
    f.close()

    # -- avoid some known lines
    w = (wl>wlmin)*(wl<wlmax)*~fl*~np.isnan(sp)

    if avoid is None:
        c = 3 if MR else 1
        # -- 2.058: HeI
        # -- 2.167: Br Gamma
        w = (np.abs(wl-2.058)>c*0.002)*(np.abs(wl-2.1665)>c*0.002)
    else:
        for _wlmin, _wlmax in avoid:
            w *= (wl<=_wlmin)+(wl>=_wlmax)

    if not quiet:
        print('WL (fit):', wl[w].shape)


    # -- FIT TELLURIC MODEL -------------------------------------------
    if MR:
        p = {'dl0':-0.000378, 'wl0':2.0, 'dl1':1.0, 'dl2':0.0, 'dl3':0.0,
             'kern':4e-3, 'kernp':.9, 'pwv':5.0, 'pow':0.85,
             'p_2.3717':0.8}
    else:
        p = {'dl0':-0.000378, 'wl0':2.0, 'dl1':1.0, 'dl2':0.0, 'dl3':0.0,
             'kern_min':2.8e-4, 'kern_max':3.4e-4, 'kernp_min':1.7, 'kernp_max':1.7, 'pwv':5.0, 'pow':0.85,
             'p_2.09913':0.8, 'p_2.11905':1.0, 'p_2.12825':1.0, 'p_2.1691':1.0, }

    # -- spectrum model using spline nodes
    for i,x in enumerate(np.linspace(wl[w].min(), wl[w].max(), 12 if MR else 35)):
        test = True
        # -- makes sure the node is not in an avoidance zone:
        if not avoid is None:
            for _wlmin, _wlmax in avoid:
                if x>=_wlmin and x<=_wlmax:
                    test = False
        if test:
            p['xS'+str(i)] = x
            p['yS'+str(i)] = np.mean(sp[w])

    fitOnly = list(filter(lambda k: k.startswith('yS'), p.keys()))
    fitOnly.append('dl0')

    doNotFit = []
    doNotFit.extend(list(filter(lambda k: k.startswith('xS'), p.keys())))
    doNotFit.extend(['wl0'])

    # == TEST
    # plt.close(0)
    # plt.figure(0)
    # plt.plot(wl[w], sp[w], '.-k')
    # plt.plot(wl[w], Ftran(wl[w], p), '-r')
    # print(p)
    # return
    # == end TEST

    fit = {'model':Ftran(wl[w], p), 'best':p}
    if True:
        if not quiet:
            print('> fit only spectrum shape, not tellurics')
        #print('wl', wl.shape, 'sp', sp.shape)
        fit = dpfit.leastsqFit(Ftran, wl[w], p, sp[w], verbose=0, fitOnly=fitOnly, maxfev=1000)
        if MR:
            doNotFit.extend(['kern', 'kernp'])
        else:
            doNotFit.extend(['kern_min', 'kern_max', 'kernp_min', 'kernp_max'])

        if not quiet:
            print('> fit all but spectral resolution (kernel)')
        fit = dpfit.leastsqFit(Ftran, wl[w], fit['best'], sp[w], verbose=0, doNotFit=doNotFit, maxfev=8000, follow=['pwv', 'pow', 'kern', 'kern_min', 'kern_max', 'kernp'])
        if not quiet:
            print('> fit everything')
            verbose=1
        else:
            verbose=0
        if MR:
            doNotFit.remove('kern')
            doNotFit.remove('kernp')
        else:
            doNotFit.remove('kern_min'); doNotFit.remove('kern_max')
            doNotFit.remove('kernp_min'); doNotFit.remove('kernp_max');
        fit = dpfit.leastsqFit(Ftran, wl[w], fit['best'], sp[w], verbose=verbose, doNotFit=doNotFit, maxfev=8000,
                               follow=['pwv', 'pow', 'kern', 'kern_min', 'kern_max', 'kernp', 'kernp_min', 'kernp_max'])

    p = {k:fit['best'][k] for k in fit['best'].keys() if not 'S' in k}
    if save:
        # -- SAVE telluric as fits extension in fits file
        f = fits.open(filename, mode='update')
        if 'TELLURICS' in f:
            f.pop('TELLURICS')
        c1 = fits.Column(name='EFF_WAVE', array=wl*1e-6, format='D', unit='m')
        c2 = fits.Column(name='RAW_SPEC', array=sp, format='D')
        c3 = fits.Column(name='TELL_TRANS', array=Ftran(wl, p), format='D')
        c4 = fits.Column(name='CORR_SPEC', array=sp/Ftran(wl, fit['best']), format='D')
        c5 = fits.Column(name='CORR_WAVE', array=Ftran(wl, fit['best'], retWL=True)*1e-6,
                        format='D', unit='m')

        hdu = fits.BinTableHDU.from_columns([c1, c2, c3, c4, c5])
        hdu.header['EXTNAME'] = 'TELLURICS'
        hdu.header['ORIGIN'] = 'https://github.com/amerand/OIUTILS'
        hdu.header['AUTHOR'] = 'amerand@eso.org'
        hdu.header['DATE'] = time.asctime()
        hdu.header['PWV'] = (round(fit['best']['pwv'], 3), 'mm of precipitable water')
        f.append(hdu)
        f.close()

    if quiet:
        return
    print('isnan:', any(np.isnan(fit['model'])))
    # -- PLOT RESULTS --------------------------------------------------
    plt.plot(wl[w], sp[w], '-c', alpha=0.5, label='raw data')
    plt.plot(wl[~w], sp[~w], '.', color='orange', alpha=0.5, label='ignored')

    #plt.plot(wl[w], fit['model'], '-k', alpha=0.2, linewidth=1, label='model')
    plt.plot(wl, Ftran(wl, fit['best']), '-k', alpha=0.2, linewidth=1, label='model')

    plt.plot(wl, sp/Ftran(wl, p)+np.median(sp)/8, '-b', label='telluric corrected + offset')
    plt.title(filename);
    plt.ylim(0.9*np.min(sp[w]), 1.1*np.max(sp[w]/Ftran(wl[w], p)+np.median(sp[w])/8))
    lines = {'HeI':[(2.0581, 2.11274, 2.11267, 2.11258, 2.161), 'c', 'dashed'],
             'HeII':((2.1885), 'c', 'dotted'),
             'MgII':((2.137, 2.143, ), '0.5', 'dashed'),
             #'MgI':((2.10655, 2.10666), '0.5', 'dotted'),
             'HI':[(2.1661, 2.360, 2.367, 2.374, 2.383, 2.392, 2.404, 2.416, 2.431, 2.449), 'b', 'dashed'],
             'H2':[(2.122), 'b', 'dotted'],
             'NaI':[(2.208, 2.208969), 'y', 'dashed'],
             'NIII':[(2.1155, 2.247, 2.251), (0,1,0.5), 'dashed'],
             'FeII':((2.089, 2.145, 2.241, 2.368), 'g', 'dashed'),
             r'$^{12}$C$^{16}$O HB':([2.2935, 2.3227, 2.3535, 2.3829, 2.4142], 'r', 'dashed'),
             r'$^{13}$C$^{16}$O HB':([2.3448, 2.3739, 2.4037, 2.4341, ], 'r', 'dotted'), #2.4971
             #'AlI':((2.109884,2.116958),(0.2,0.5,0.8), 'dotted'),
             #'MgI':((2.121393,2.146472,2.386573),'r'),
             #'ScI':((2.20581,2.20714),'m'),
             #'SiII':((2.200),'g'),
             'CaI':((1.99318, 2.261410, 2.263110, 2.265741),'g', 'dotted'), #1.89282, 1.94508, 1.98702,
             }
    for k in list(lines.keys()):
        plt.vlines(lines[k][0], plt.ylim()[0], plt.ylim()[1], color=lines[k][1],
                linestyle=lines[k][2], label=k, alpha=0.3, linewidth=1)
    plt.legend(fontsize=6, ncol=4)
    try:
        plt.tight_layout()
    except:
        pass
    return

def showTellurics(filename, fig=0):
    if not fig is None:
        plt.close(fig)
        plt.figure(0)
    h = fits.open(filename)
    plt.plot(h['TELLURICS'].data['EFF_WAVE']*1e6,
             h['TELLURICS'].data['RAW_SPEC'],
             '-y', alpha=0.5, label='raw spectrum')
    plt.plot(h['TELLURICS'].data['EFF_WAVE']*1e6,
             h['TELLURICS'].data['RAW_SPEC']/h['TELLURICS'].data['TELL_TRANS'],
             '-k', label='corrected spectrum')
    plt.plot(h['TELLURICS'].data['EFF_WAVE']*1e6,
             h['TELLURICS'].data['TELL_TRANS']*np.mean(h['TELLURICS'].data['RAW_SPEC']),
             '-b', label='telluric model', alpha=0.5)
    plt.legend()
    plt.title(filename, fontsize=7)
    plt.xlabel('wavelength ($\mu$m)')
    plt.ylabel("flux (arb. unit)")

    h.close()
    return
