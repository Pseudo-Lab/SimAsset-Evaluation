"""Explicit-subscription preflight and bounded command with VM deallocation.

This never creates/starts a VM. 'run' is for an already approved, dedicated VM.
Configuration lives outside Git; plan examples are not spending approval.
"""
import argparse
from datetime import datetime,timedelta,timezone
import json
import math
from pathlib import Path
import subprocess
from uuid import UUID

OWNER='simasset-personal-gpu-lab'


def validate_config(c,paid=False):
    for k in ('subscription_id','tenant_id'): UUID(c[k])
    if c['resource_group']!='rg-simasset-personal-gpu-lab': raise ValueError('Dedicated resource group required')
    if paid:
        budget=c.get('approval',{})
        if budget.get('approved') is not True or not budget.get('human_reference'):
            raise ValueError('Explicit human budget authorization is required')
        hours=budget.get('max_hours',0);cap=budget.get('cap_usd',0)
        rate=budget.get('vm_hourly_usd',0);other=budget.get('reserved_non_compute_usd',-1)
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in (hours,cap,rate,other)):
            raise ValueError('Finite numeric budget fields required')
        if not 0<hours<=6 or cap<=0 or rate<=0 or other<0 or hours*rate+other>cap:
            raise ValueError('Time/rate/reserve exceeds approved budget')
    return c


def az(c,*args):
    result=subprocess.run(['az',*args,'--subscription',c['subscription_id'],'--only-show-errors','-o','json'],
                          text=True,capture_output=True,check=True,timeout=300)
    return json.loads(result.stdout) if result.stdout.strip() else None


def expected_vm(c):
    name=c.get('vm_name','')
    if not name or '/' in name: raise ValueError('One explicit VM name required')
    return f"/subscriptions/{c['subscription_id']}/resourceGroups/{c['resource_group']}/providers/Microsoft.Compute/virtualMachines/{name}"


def verify_vm(c,vm):
    if vm['id'].casefold()!=expected_vm(c).casefold() or vm.get('tags',{}).get('purpose')!=OWNER:
        raise ValueError('VM identity/ownership differs; no action taken')
    if vm.get('location')!=c['location'] or vm.get('hardwareProfile',{}).get('vmSize')!=c['vm_size']:
        raise ValueError('VM region/size differs from the cost assumptions')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['preflight','run'])
    ap.add_argument('--config',type=Path,required=True);ap.add_argument('--evidence',type=Path,required=True)
    ap.add_argument('--command',nargs=argparse.REMAINDER,default=[])
    args=ap.parse_args();c=validate_config(json.loads(args.config.read_text()),paid=args.action=='run')
    account=az(c,'account','show')
    if account['id']!=c['subscription_id'] or account['tenantId']!=c['tenant_id'] or account['state']!='Enabled':
        raise SystemExit('Unexpected subscription, tenant or account state')
    report={'at':datetime.now(timezone.utc).isoformat(),'subscription_id':account['id'],'tenant_id':account['tenantId'],
            'usage':az(c,'vm','list-usage','--location',c['location']),
            'skus':az(c,'vm','list-skus','--location',c['location'],'--size',c['vm_size'],'--all')}
    exists=az(c,'group','exists','--name',c['resource_group'])
    report['resource_group_exists']=exists
    report['resources']=az(c,'resource','list','--resource-group',c['resource_group']) if exists else []
    if args.evidence.exists(): raise SystemExit('Use a new evidence path; previous records are immutable')
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(report,indent=2))
    if args.action=='preflight': print('Preflight saved; no resources changed');return
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    if not command: raise SystemExit('Provide the bounded experiment command after --command')
    vm=az(c,'vm','show','--ids',expected_vm(c));verify_vm(c,vm)
    deadline=datetime.now(timezone.utc)+timedelta(hours=c['approval']['max_hours'],minutes=1)
    try:
        # Management-plane schedule survives a lost local connection. It is a
        # deadline fallback, not a guaranteed billing cap or deletion policy.
        az(c,'vm','auto-shutdown','--ids',expected_vm(c),'--time',deadline.strftime('%H%M'),'--location',c['location'])
        report['shutdown_deadline_utc']=deadline.isoformat()
        args.evidence.write_text(json.dumps(report,indent=2))
        result=subprocess.run(command,timeout=c['approval']['max_hours']*3600,check=True)
        report['command_exit_code']=result.returncode
    except BaseException as e:
        report['command_error']=f'{type(e).__name__}: {e}'
        raise
    finally:
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        cleanup_error=None
        try:
            az(c,'vm','deallocate','--ids',expected_vm(c))
            state=az(c,'vm','get-instance-view','--ids',expected_vm(c))
            statuses=state.get('instanceView',state).get('statuses',[])
            report['deallocated']=any(x.get('code')=='PowerState/deallocated' for x in statuses)
            if not report['deallocated']: raise RuntimeError('VM deallocation was not confirmed')
        except Exception as e:
            report['deallocation_error']=f'{type(e).__name__}: {e}'
            cleanup_error=e
        try:
            report['remaining_resources']=az(c,'resource','list','--resource-group',c['resource_group'])
        except Exception as e:
            report['remaining_resources_error']=f'{type(e).__name__}: {e}'
            cleanup_error=cleanup_error or e
        finally:
            args.evidence.write_text(json.dumps(report,indent=2))
        if cleanup_error:
            raise RuntimeError('Cloud cleanup or retained-resource inventory could not be confirmed; see evidence') from cleanup_error
    print('VM deallocation confirmed. Review retained disks/IPs and Cost Management separately.')


if __name__=='__main__': main()
